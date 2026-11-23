import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt


_STAGE_BATCH_DOCTYPES = {
    1: "Stage 1 Batch",
    2: "Stage 2 Batch",
    3: "Stage 3 Batch",
}
_CHILD_TABLES = (
    ("Stage 2 Batch", "Stage 2 Batch Item"),
    ("Stage 3 Batch", "Stage 2 Batch Item"),
    ("Belt Batch", "Belt Batch Item"),
)


def _batch_stage(doc):
    if doc.doctype == "Belt Batch":
        return cint(doc.get("process_step") or re.sub(r"\D", "", str(doc.get("stage") or "")))
    return cint(getattr(type(doc), "STAGE", 0))


def _stage_index(value):
    match = re.search(r"\d+", str(value or ""))
    return cint(match.group()) if match else 0


def _source_doc(doctype, name):
    if not doctype or not name or not frappe.db.exists(doctype, name):
        return None
    return frappe.get_doc(doctype, name)


def _batch_consumption(source_name, exclude_doctype=None, exclude_name=None, lock=False):
    consumed = 0.0
    for parent_doctype, child_doctype in _CHILD_TABLES:
        if not frappe.db.exists("DocType", parent_doctype) or not frappe.db.exists("DocType", child_doctype):
            continue
        if not frappe.db.has_column(child_doctype, "source_batch"):
            continue
        params = {"source_name": source_name}
        exclude = ""
        if parent_doctype == exclude_doctype and exclude_name:
            exclude = " AND parent.name != %(exclude_name)s"
            params["exclude_name"] = exclude_name
        query = f"""
            SELECT child.actual_utilization
            FROM `tab{child_doctype}` child
            INNER JOIN `tab{parent_doctype}` parent ON parent.name = child.parent
            WHERE child.source_batch = %(source_name)s
              AND parent.is_completed = 1{exclude}
            ORDER BY child.name
        """
        if lock:
            values = frappe.db.sql(query + " FOR UPDATE", params)
            consumed += sum(flt(value[0]) for value in values)
        else:
            value = frappe.db.sql(f"SELECT COALESCE(SUM(used.actual_utilization), 0) FROM ({query}) used", params)
            consumed += flt(value[0][0] if value else 0)
    return consumed


def _batch_output_stage(doc):
    if doc.doctype == "Belt Batch":
        return _stage_index(doc.get("process_step") or doc.get("stage"))
    return cint(getattr(type(doc), "STAGE", 0))


def get_available_source_batches(product, stage, exclude_doctype=None, exclude_name=None):
    """Return completed batches at a product's prior stage with their live balance."""
    stage = cint(stage)
    if not product or stage < 1:
        return []

    candidates = []
    standard_doctype = _STAGE_BATCH_DOCTYPES.get(stage)
    doctypes = [standard_doctype] if standard_doctype else []
    if frappe.db.exists("DocType", "Belt Batch"):
        doctypes.append("Belt Batch")

    for doctype in doctypes:
        if not doctype or not frappe.db.exists("DocType", doctype):
            continue
        fields = ["name", "product", "quantity", "unit_cost", "batch_total"]
        filters = {"product": product, "is_completed": 1}
        if doctype == "Belt Batch":
            fields += ["process_step", "stage"]
        rows = frappe.get_all(doctype, filters=filters, fields=fields, order_by="creation asc, name asc")

        for row in rows:
            doc_stage = _stage_index(row.get("process_step") or row.get("stage")) if doctype == "Belt Batch" else stage
            if doc_stage != stage:
                continue
            quantity = flt(row.get("quantity"))
            consumed = _batch_consumption(
                row.name,
                exclude_doctype=exclude_doctype,
                exclude_name=exclude_name,
            )
            available = max(0.0, quantity - consumed)
            if available <= 1e-9:
                continue
            unit_cost = flt(row.get("unit_cost"))
            if not unit_cost and quantity:
                unit_cost = flt(row.get("batch_total")) / quantity
            candidates.append({
                "source_batch": row.name,
                "source_batch_doctype": doctype,
                "product": product,
                "source_stage": f"Stage {stage}",
                "batch_available_qty": quantity,
                "batch_consumed_qty": consumed,
                "batch_remaining_qty": available,
                "unit_price": unit_cost,
                "unit_cost": unit_cost,
            })
    return candidates


def expand_stage_source_rows(rows, current_stage, is_belt=False, exclude_doctype=None, exclude_name=None):
    """Expand previous-stage input rows to one selectable row per eligible source batch."""
    stage = cint(current_stage)
    if stage <= 1:
        return rows
    expanded = []
    for row in rows:
        source_stage = _stage_index(row.get("source_stage"))
        is_previous_stage_input = bool(cint(row.get("is_carried_in"))) or (
            is_belt and stage == 2 and source_stage == stage - 1
        )
        if not is_previous_stage_input or source_stage != stage - 1:
            expanded.append(row)
            continue

        batches = get_available_source_batches(
            row.get("product"),
            stage - 1,
            exclude_doctype=exclude_doctype,
            exclude_name=exclude_name,
        )
        if not batches:
            u_qty = row.get("total_utilization") or flt(row.get("per_unit_utilization", 1))
            row["actual_utilization"] = u_qty
            row["actual_amount"] = flt(u_qty) * flt(row.get("unit_price", 0))
            expanded.append(row)
            continue

        for batch in batches:
            batch_row = dict(row)
            batch_row.update(batch)
            batch_row["per_unit_utilization"] = 0
            batch_row["total_utilization"] = 0
            batch_row["actual_utilization"] = 0
            batch_row["amount"] = 0
            batch_row["per_unit_amount"] = 0
            batch_row["actual_amount"] = 0
            expanded.append(batch_row)
    return expanded


def source_batch_unit_cost(row):
    batch = _source_doc(row.get("source_batch_doctype"), row.get("source_batch"))
    if not batch:
        return None
    cost = flt(batch.get("unit_cost"))
    if not cost and flt(batch.get("quantity")):
        cost = flt(batch.get("batch_total")) / flt(batch.get("quantity"))
    return cost


def validate_source_batch_consumption(doc, lock=False):
    """Validate selected batch quantities against completed upstream balances."""
    stage = _batch_stage(doc)
    if stage <= 1:
        return
    allocations = defaultdict(float)
    required_products = set()
    selected_products = defaultdict(float)
    for row in doc.get("items") or []:
        quantity = flt(row.get("actual_utilization"))
        if quantity < 0:
            frappe.throw(_("Selected source quantity cannot be negative."))
        source_name = row.get("source_batch")
        source_stage = _stage_index(row.get("source_stage")) or (
            stage - 1 if cint(row.get("is_carried_in")) else 0
        )
        requires_batch = source_stage == stage - 1 and (
            cint(row.get("is_carried_in"))
            or (doc.doctype == "Belt Batch" and stage == 2)
        )
        if requires_batch and not source_name and lock:
            frappe.throw(_("Select a completed Stage {0} source batch for {1}.").format(
                stage - 1, row.get("product") or doc.get("product")
            ))
        if requires_batch and lock:
            required_products.add(row.get("product") or doc.get("product"))
        if not source_name:
            continue
        source_doctype = row.get("source_batch_doctype")
        allowed_doctypes = {_STAGE_BATCH_DOCTYPES.get(stage - 1), "Belt Batch"}
        allowed_doctypes.discard(None)
        if source_doctype and source_doctype not in allowed_doctypes:
            frappe.throw(_("Invalid source batch type for Stage {0}.").format(stage))
        if not source_doctype:
            matches = [dt for dt in allowed_doctypes if frappe.db.exists(dt, source_name)]
            if len(matches) != 1:
                frappe.throw(_("Could not identify source batch {0}.").format(source_name))
            source_doctype = matches[0]
            row.source_batch_doctype = source_doctype
        source = _source_doc(source_doctype, source_name)
        if not source or not cint(source.get("is_completed")):
            frappe.throw(_("Source batch {0} must be completed before it can be consumed.").format(source_name))
        if _batch_output_stage(source) != stage - 1:
            frappe.throw(_("Source batch {0} is not from Stage {1}.").format(source_name, stage - 1))
        if source.get("product") != row.get("product"):
            frappe.throw(_("Source batch {0} does not produce {1}.").format(source_name, row.get("product")))
        if quantity <= 0:
            continue
        key = (source_doctype, source_name)
        allocations[key] += quantity
        selected_products[row.get("product") or doc.get("product")] += quantity

    for product in required_products:
        if selected_products[product] <= 0:
            frappe.throw(_("Select a positive quantity from an eligible Stage {0} batch for {1}.").format(
                stage - 1, product
            ))

    for (doctype, name), selected in sorted(allocations.items()):
        if lock:
            frappe.db.sql(f"SELECT name FROM `tab{doctype}` WHERE name = %s FOR UPDATE", name)
        source = _source_doc(doctype, name)
        consumed = _batch_consumption(
            name,
            exclude_doctype=doc.doctype,
            exclude_name=doc.name,
            lock=lock,
        )
        available = max(0.0, flt(source.get("quantity")) - consumed)
        if selected > available + 1e-9:
            frappe.throw(
                _("Selected quantity {0} exceeds the {1} available from batch {2}.").format(
                    selected, available, name
                )
            )


def ensure_belt_batch_tracking_fields():
    """Add source traceability fields to the dynamically-created Belt Batch child table."""
    if not frappe.db.exists("DocType", "Belt Batch Item"):
        return
    fields = (
        ("source_stage", "Data", "Source Stage"),
        ("source_batch", "Data", "Source Batch"),
        ("source_batch_doctype", "Data", "Source Batch DocType"),
        ("batch_available_qty", "Float", "Batch Available Qty"),
        ("batch_consumed_qty", "Float", "Batch Consumed Qty"),
        ("batch_remaining_qty", "Float", "Batch Remaining Qty"),
    )
    for fieldname, fieldtype, label in fields:
        if frappe.get_meta("Belt Batch Item").has_field(fieldname):
            continue
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Belt Batch Item",
            "fieldname": fieldname,
            "label": label,
            "fieldtype": fieldtype,
            "insert_after": "is_carried_in",
        }).insert(ignore_permissions=True)
    frappe.clear_cache(doctype="Belt Batch Item")
