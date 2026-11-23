import frappe
from frappe import _
from frappe.model.document import Document


class RejectionReason(Document):
    def validate(self):
        self.reason_name = (self.reason_name or "").strip()
        if not self.reason_name:
            frappe.throw(_("Rejection Reason is required."))

    def on_trash(self):
        frappe.throw(_("Rejection reasons cannot be deleted. Deactivate the reason to preserve historical records."))
