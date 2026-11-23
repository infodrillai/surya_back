import frappe
from frappe import _
from frappe.utils import cint, flt

from clssurya.utils.base import require_admin
from clssurya.utils.batch_tracking import source_batch_unit_cost, validate_source_batch_consumption
from clssurya.utils.stock_service import inventory_price, post, reverse


def _stage(doc):
    return cint(doc.get("process_step") or doc.get("stage"))


def _route_steps(product):
    recipe = None
    if frappe.db.exists("Belt Production", product):
        recipe = frappe.get_doc("Belt Production", product)
    elif frappe.db.exists("BOM", product):
        recipe = frappe.get_doc("BOM", product)
    return cint(getattr(recipe, "total_steps", 0)) or cint(
        frappe.db.get_value("Product", product, "total_steps")
    ) or 4


def _calculate(doc):
    stage = _stage(doc)
    quantity = flt(doc.get("quantity"))
    carried_cost = 0.0
    added_cost = 0.0

    for row in doc.get("items") or []:
        actual = flt(row.get("actual_utilization"))
        if actual < 0:
            frappe.throw(_("Actual material quantity cannot be negative."))
        source_stage = row.get("source_stage")
        source_price = source_batch_unit_cost(row) if row.get("source_batch") else None
        if source_price is not None:
            row.unit_price = source_price
        else:
            row.unit_price = inventory_price(
                row.product,
                source_stage or (f"Stage {stage - 1}" if row.get("is_carried_in") else "Raw"),
            )
        row.actual_amount = actual * flt(row.unit_price)
        row.total_utilization = flt(row.get("per_unit_utilization")) * quantity
        row.amount = flt(row.total_utilization) * flt(row.unit_price)
        row_extra = flt(row.get("extra_cost")) * quantity
        if row.get("source_batch") or cint(row.get("is_carried_in")):
            carried_cost += flt(row.actual_amount)
        else:
            added_cost += flt(row.actual_amount) + row_extra

    charge_total = 0.0
    for charge in doc.get("charges") or []:
        basis = charge.get("calculation_basis") or "Per Piece"
        charge_qty = flt(charge.get("quantity")) or (quantity if basis == "Per Piece" else 1)
        charge.amount = flt(charge.get("per_unit_price")) * charge_qty
        charge_total += flt(charge.amount)
    added_cost += charge_total

    base_cost = carried_cost + added_cost
    rejection_per_piece = flt(doc.get("rejection_per_piece"))
    rejection_percent = flt(doc.get("rejection_percent"))
    rejection_amount = (
        rejection_per_piece * quantity
        if rejection_per_piece > 0
        else base_cost * rejection_percent / 100
    )
    rejected_qty = flt(doc.get("rejected_qty"))
    if rejection_percent > 0 and not rejected_qty:
        rejected_qty = quantity * rejection_percent / 100
    total_cost = base_cost + rejection_amount
    good_quantity = max(0.0, quantity - rejected_qty)

    doc.carried_cost = carried_cost
    doc.added_cost = added_cost
    doc.charge_total = charge_total
    doc.rejection_amount = rejection_amount
    doc.batch_total = total_cost
    doc.unit_cost = total_cost / (good_quantity or quantity) if quantity else 0
    doc.rejected_qty = rejected_qty
    doc.input_qty = quantity + rejected_qty
    doc.pending_qty = 0


def validate(doc, method=None):
    if not doc.get("product"):
        return
    stage = _stage(doc)
    if stage < 1 or stage > 4:
        frappe.throw(_("Production stage must be between 1 and 4."))
    if stage > _route_steps(doc.product):
        frappe.throw(_("{0} is not configured for Stage {1}.").format(doc.product, stage))
    if flt(doc.get("quantity")) <= 0:
        frappe.throw(_("Quantity produced must be greater than zero."))
    if flt(doc.get("rejection_percent")) < 0 or flt(doc.get("rejection_percent")) >= 100:
        frappe.throw(_("Rejection percent must be from 0 to less than 100."))

    previous = doc.get_doc_before_save()
    if previous and cint(previous.get("is_completed")):
        if cint(doc.get("is_completed")):
            frappe.throw(_("Completed Belt Batches are locked. Reopen them before editing."))
        require_admin()

    _calculate(doc)
    validate_source_batch_consumption(doc)
    from clssurya.utils.rejections import validate_belt_batch_rejections

    validate_belt_batch_rejections(doc, method)


def _stock_entries(doc):
    stage = _stage(doc)
    entries = []
    for row in doc.get("items") or []:
        quantity = flt(row.get("actual_utilization"))
        if quantity:
            source_stage = row.get("source_stage") or (
                f"Stage {stage - 1}" if row.get("source_batch") or row.get("is_carried_in") else "Raw"
            )
            entries.append({"product": row.product, "stage": source_stage, "qty": -quantity})
    entries.append({
        "product": doc.product,
        "stage": f"Stage {stage}",
        "qty": flt(doc.quantity),
        "unit_price": flt(doc.unit_cost),
    })
    return entries


def on_update(doc, method=None):
    previous = doc.get_doc_before_save()
    if not previous:
        return
    was_completed = cint(previous.get("is_completed"))
    is_completed = cint(doc.get("is_completed"))
    if is_completed and not was_completed:
        validate_source_batch_consumption(doc, lock=True)
        post(_stock_entries(doc), "Belt Batch", doc.name)
        from clssurya.utils.rejections import sync_rejection_entry

        sync_rejection_entry(doc)
    elif was_completed and not is_completed:
        require_admin()
        reverse("Belt Batch", doc.name)
        from clssurya.utils.rejections import deactivate_rejection_entry

        deactivate_rejection_entry(doc)


def on_trash(doc, method=None):
    if cint(doc.get("is_completed")):
        frappe.throw(_("A completed Belt Batch cannot be deleted. Reopen it first."))
    from clssurya.utils.rejections import clear_rejection_entry

    clear_rejection_entry(doc)
