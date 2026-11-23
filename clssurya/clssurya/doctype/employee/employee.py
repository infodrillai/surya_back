import frappe
from frappe import _
from frappe.model.document import Document


class Employee(Document):
    def validate(self):
        self.employee_name = (self.employee_name or "").strip()
        self.department = (self.department or "").strip()
        if not self.employee_name or not self.department:
            frappe.throw(_("Employee Name and Department are required."))
        if self.status not in ("Active", "Inactive"):
            frappe.throw(_("Employee status must be Active or Inactive."))

    def on_trash(self):
        frappe.throw(_("Employees cannot be deleted. Set the employee status to Inactive to preserve historical records."))
