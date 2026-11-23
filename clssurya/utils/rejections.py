import frappe
from frappe import _
from frappe.utils import flt, getdate


PRODUCTION_TYPES = {
    "Stage 1 Batch": ("PU Production", "PU Production"),
    "Stage 2 Batch": ("PU Production", "PU Production"),
    "Stage 3 Batch": ("PU Production", "PU Production"),
    "Belt Batch": ("Belt Production", "Belt Production"),
    "CNC Machine Log": ("CNC Operation", "CNC Operation"),
    "Bonding Log": ("Bonding", "Bonding"),
    "Coating Log": ("Coating", "Coating"),
    "External Grinding Log": ("External Grinding", "External Grinding"),
}


def _employee_reference(doc):
    if doc.get("employee") and frappe.db.exists("Employee", doc.employee):
        return doc.employee
    legacy = (doc.get("operator") or "").strip()
    if not legacy:
        return None
    return frappe.db.get_value("Employee", {"employee_name": legacy}, "name") or (
        legacy if frappe.db.exists("Employee", legacy) else None
    )


def _active_reason(value):
    if not value:
        return None
    if frappe.db.exists("Rejection Reason", value):
        return value
    return frappe.db.get_value("Rejection Reason", {"reason_name": value, "is_active": 1}, "name")


def sync_legacy_operator(doc, method=None):
    """Keep reports that still read the legacy text field showing the linked employee."""
    employee = doc.get("employee")
    if employee and frappe.db.exists("Employee", employee) and doc.meta.has_field("operator"):
        doc.operator = frappe.db.get_value("Employee", employee, "employee_name")


def validate_active_references(doc, method=None):
    """Require active employee/reason references on new assignments, retain old links."""
    old = doc.get_doc_before_save()
    employee = doc.get("employee")
    if employee and (not old or old.get("employee") != employee):
        if frappe.db.get_value("Employee", employee, "status") != "Active":
            frappe.throw(_("Choose an active employee for a new production entry."))
    reason = doc.get("rejection_reason")
    if reason and flt(doc.get("rejected_qty")) > 0 and (not old or old.get("rejection_reason") != reason):
        if not frappe.db.get_value("Rejection Reason", reason, "is_active"):
            frappe.throw(_("Choose an active rejection reason."))


def sync_rejection_entry(doc, method=None):
    """Mirror completed production rejection once, retaining a trace on reopen."""
    if doc.doctype not in PRODUCTION_TYPES or not frappe.db.exists("DocType", "Rejection Entry"):
        return
    source_key = f"PRODUCTION_REJECTION::{doc.doctype}::{doc.name}"
    existing = frappe.db.get_value("Rejection Entry", {"source_doctype": doc.doctype, "source_name": doc.name}, "name")
    existing = existing or frappe.db.get_value("Rejection Entry", {"source_key": f"{doc.doctype}::{doc.name}"}, "name")
    is_completed = bool(flt(doc.get("is_completed")) or doc.get("status") == "Completed" or flt(doc.get("docstatus")) == 1)
    rejected = flt(doc.get("rejected_qty")) if is_completed else 0
    if rejected <= 0:
        if existing:
            frappe.db.set_value("Rejection Entry", existing, "rejected_qty", 0, update_modified=False)
        return

    department, production_type = PRODUCTION_TYPES[doc.doctype]
    process = doc.get("operation") or doc.get("process")
    if not process:
        process_label = doc.get("current_process") or doc.get("operation_sequence")
        if process_label:
            process = frappe.db.get_value("Process", {"process_name": process_label}, "name")
            process = process or (process_label if frappe.db.exists("Process", process_label) else None)
    date_field = "production_date" if doc.doctype in ("CNC Machine Log", "Bonding Log") else (
        "coating_date" if doc.doctype == "Coating Log" else "outward_date" if doc.doctype == "External Grinding Log" else "posting_date"
    )
    input_qty = flt(doc.get("input_qty") or doc.get("sent_qty") or doc.get("returned_qty") or rejected)
    good_qty = flt(doc.get("accepted_qty") or doc.get("good_qty") or doc.get("quantity"))
    pending_qty = flt(doc.get("pending_qty") or doc.get("remaining_qty"))
    # PU StageBatch input_qty is the sum of material consumption, which may use
    # a different UOM from the finished product. Use finished-output quantities
    # only when calculating product rejection totals.
    if doc.doctype in ("Stage 1 Batch", "Stage 2 Batch", "Stage 3 Batch"):
        good_qty = flt(doc.get("quantity"))
        pending_qty = 0
        input_qty = good_qty + rejected
    # Reconcile at the finished product UOM without combining material units.
    input_qty = max(input_qty, good_qty + rejected + pending_qty)
    data = {
        "rejection_date": doc.get(date_field) or getdate(),
        "department": department,
        "production_type": production_type,
        "production_reference": doc.get("production_batch") or doc.get("batch_reference") or doc.get("job_reference") or doc.name,
        "product": doc.get("product"),
        "batch_id": doc.get("production_batch") or doc.get("batch_reference") or doc.get("job_reference") or doc.name,
        "process": process,
        "machine": doc.get("machine"),
        "employee": _employee_reference(doc),
        "shift": doc.get("shift"),
        "input_qty": input_qty,
        "good_qty": good_qty,
        "rejected_qty": rejected,
        "pending_qty": pending_qty,
        "uom": doc.get("uom") or (frappe.db.get_value("Product", doc.get("product"), "uom") if doc.get("product") else None),
        "rejection_reason": _active_reason(doc.get("rejection_reason")),
        "rejection_status": doc.get("rejection_status") or "Pending Inspection",
        "remarks": doc.get("remarks"),
        "source_doctype": doc.doctype,
        "source_name": doc.name,
        "source_key": source_key,
    }
    if data["rejection_status"] not in ("Pending Inspection", "Rework", "Scrap", "Inspection Hold"):
        data["rejection_status"] = "Pending Inspection"

    if existing:
        rejection = frappe.get_doc("Rejection Entry", existing)
        # Status decisions made by inspectors are kept when the source operation
        # is edited; only source facts are synchronized.
        status = rejection.rejection_status
        data["rejection_status"] = status
        rejection.update(data)
        rejection.flags.from_production_sync = True
        rejection.save(ignore_permissions=True)
    else:
        rejection = frappe.get_doc({"doctype": "Rejection Entry", **data})
        rejection.flags.from_production_sync = True
        rejection.insert(ignore_permissions=True)


def clear_rejection_entry(doc, method=None):
    """Keep a traceable zero-quantity record when its production source is removed."""
    existing = frappe.db.get_value("Rejection Entry", {"source_doctype": doc.doctype, "source_name": doc.name}, "name")
    existing = existing or frappe.db.get_value("Rejection Entry", {"source_key": f"{doc.doctype}::{doc.name}"}, "name")
    if existing:
        frappe.db.set_value("Rejection Entry", existing, "rejected_qty", 0, update_modified=False)


def deactivate_rejection_entry(doc, method=None):
    """Keep the generated row for audit, but exclude it while the source is reopened."""
    clear_rejection_entry(doc, method)


def seed_rejection_reasons():
    """Install editable starter reasons once; administrators can change or deactivate them."""
    if not frappe.db.exists("DocType", "Rejection Reason"):
        return
    for label in (
        "Incorrect Cutting", "Wrong Dimension", "Surface Defect", "Material Defect",
        "Machine Error", "Coating Defect", "Bonding Defect", "Shape Defect", "Other",
    ):
        if not frappe.db.exists("Rejection Reason", {"reason_name": label}):
            frappe.get_doc({"doctype": "Rejection Reason", "reason_name": label, "is_active": 1}).insert(ignore_permissions=True)


def ensure_belt_batch_fields():
    """Add the shared employee/rejection fields to the site's custom Belt Batch DocType."""
    if not frappe.db.exists("DocType", "Belt Batch"):
        return
    fields = [
        ("employee", "Link", "Employee / Operator", "Employee"),
        ("machine", "Link", "Machine", "CNC Machine"),
        ("shift", "Select", "Shift", "Morning\nEvening\nNight"),
        ("input_qty", "Float", "Input Quantity", None),
        ("rejected_qty", "Float", "Rejected Quantity", None),
        ("pending_qty", "Float", "Pending Quantity", None),
        ("rejection_reason", "Link", "Rejection Reason", "Rejection Reason"),
        ("rejection_status", "Select", "Rejection Status", "Pending Inspection\nRework\nScrap\nInspection Hold\nApproved Rejection"),
    ]
    for fieldname, fieldtype, label, options in fields:
        if frappe.get_meta("Belt Batch").has_field(fieldname):
            continue
        field = {"doctype": "Custom Field", "dt": "Belt Batch", "fieldname": fieldname,
                 "label": label, "fieldtype": fieldtype, "insert_after": "posting_date"}
        if options:
            field["options"] = options
        if fieldname == "rejection_status":
            field["default"] = "Pending Inspection"
        elif fieldname == "rejected_qty":
            field["default"] = "0"
        frappe.get_doc(field).insert(ignore_permissions=True)
    frappe.clear_cache(doctype="Belt Batch")


def validate_belt_batch_rejections(doc, method=None):
    rejected = flt(doc.get("rejected_qty"))
    good = flt(doc.get("quantity"))
    if rejected < 0 or good < 0 or flt(doc.get("input_qty")) < 0:
        frappe.throw(_("Production quantities cannot be negative."))
    if rejected and not flt(doc.get("input_qty")):
        doc.input_qty = good + rejected
    input_qty = flt(doc.get("input_qty"))
    if input_qty and good + rejected > input_qty:
        frappe.throw(_("Good plus Rejected quantity cannot exceed Input Quantity."))
    if input_qty:
        doc.pending_qty = input_qty - good - rejected
    validate_active_references(doc)
