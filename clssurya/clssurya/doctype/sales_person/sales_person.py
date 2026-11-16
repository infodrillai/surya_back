import frappe
from frappe import _
from frappe.model.document import Document

class SalesPerson(Document):
    def validate(self):
        if self.assigned_user:
            # Check for unique user assignment
            existing = frappe.db.get_value(
                "Sales Person",
                {"assigned_user": self.assigned_user, "name": ["!=", self.name]},
                "name"
            )
            if existing:
                frappe.throw(_("User {0} is already assigned to Sales Person {1}").format(
                    self.assigned_user, existing
                ))
