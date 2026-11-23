import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

STATUSES = {"Pending Inspection", "Rework", "Scrap", "Inspection Hold", "Approved Rejection"}
TRANSITIONS = {
    "Pending Inspection": {"Pending Inspection", "Rework", "Scrap", "Inspection Hold", "Approved Rejection"},
    "Rework": {"Pending Inspection", "Rework", "Scrap", "Inspection Hold", "Approved Rejection"},
    "Inspection Hold": {"Pending Inspection", "Rework", "Scrap", "Inspection Hold", "Approved Rejection"},
    "Scrap": {"Scrap", "Approved Rejection"},
    "Approved Rejection": {"Approved Rejection"},
}


class RejectionEntry(Document):
    def validate(self):
        for field in ("input_qty", "good_qty", "rejected_qty", "pending_qty"):
            if flt(self.get(field)) < 0:
                frappe.throw(_("{0} cannot be negative.").format(field.replace("_", " ").title()))
        total = flt(self.good_qty) + flt(self.rejected_qty) + flt(self.pending_qty)
        if flt(self.rejected_qty) > 0 and not flt(self.input_qty):
            frappe.throw(_("Input Quantity is required when rejected quantity is recorded."))
        if flt(self.input_qty) and total > flt(self.input_qty) + 1e-9:
            frappe.throw(_("Good, rejected, and pending quantities cannot exceed input quantity."))
        if flt(self.input_qty):
            self.pending_qty = max(0, flt(self.input_qty) - flt(self.good_qty) - flt(self.rejected_qty))
        if not self.department:
            frappe.throw(_("Department is required."))
        if self.rejection_status not in STATUSES:
            frappe.throw(_("Select a valid rejection status."))
        if self.rejection_reason and not frappe.db.get_value("Rejection Reason", self.rejection_reason, "is_active"):
            old = self.get_doc_before_save()
            if not old or old.rejection_reason != self.rejection_reason:
                frappe.throw(_("Select an active rejection reason for new entries."))

        old = self.get_doc_before_save()
        if old and old.source_key and old.source_key.startswith("PRODUCTION_REJECTION::") and not self.flags.get("from_production_sync"):
            source_fields = ("rejection_date", "department", "production_type", "production_reference", "product", "batch_id", "process", "machine", "employee", "shift", "input_qty", "good_qty", "rejected_qty", "pending_qty", "uom", "source_doctype", "source_name", "source_key")
            if any(old.get(field) != self.get(field) for field in source_fields):
                frappe.throw(_("Production quantities and source references are maintained from the production batch."))
        if not self.flags.get("from_production_sync") and self.employee and frappe.db.get_value("Employee", self.employee, "status") != "Active" and (not old or old.employee != self.employee):
            frappe.throw(_("Select an active employee for a new rejection entry."))
        if old and self.rejection_status not in TRANSITIONS.get(old.rejection_status, set()):
            frappe.throw(_("This rejection status transition is not allowed."))
        if not self.flags.get("from_production_sync") and self.rejection_status == "Approved Rejection" and (not old or old.rejection_status != "Approved Rejection") and not frappe.has_role("System Manager") and not frappe.has_role("CS Admin"):
            frappe.throw(_("Only an administrator can approve a rejection."))
        if not self.flags.get("from_production_sync") and old and old.rejection_status == "Approved Rejection" and not frappe.has_role("System Manager") and not frappe.has_role("CS Admin"):
            frappe.throw(_("Approved rejection records can only be changed by an administrator."))

    def before_insert(self):
        if self.production_type in ("PU Production", "Belt Production"):
            source_doctypes = {
                "PU Production": {"Stage 1 Batch", "Stage 2 Batch", "Stage 3 Batch"},
                "Belt Production": {"Belt Batch"},
            }
            if self.source_doctype not in source_doctypes[self.production_type] or not self.source_name:
                frappe.throw(_("{0} rejection entries are created automatically from completed production batches.").format(self.production_type))
            if not frappe.db.exists(self.source_doctype, self.source_name):
                frappe.throw(_("The linked production batch does not exist."))
            if not self.source_key or not self.source_key.startswith(f"PRODUCTION_REJECTION::{self.source_doctype}::{self.source_name}"):
                frappe.throw(_("A valid automatic source reference is required for this production rejection."))
        if not self.source_key:
            self.source_key = f"MANUAL::{frappe.generate_hash(length=20)}"
