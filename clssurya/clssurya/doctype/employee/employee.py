import frappe
from frappe import _
from frappe.model.document import Document
import re


def sync_employee_naming_series():
    """Align the EMP series with existing IDs, not a stale counter."""
    if not frappe.db.exists("DocType", "Employee"):
        return
    names = frappe.get_all("Employee", pluck="name", ignore_permissions=True)
    max_used = max((int(match.group(1)) for name in names if (match := re.fullmatch(r"EMP-(\d+)", name or ""))), default=0)
    frappe.db.sql(
        "INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE `current` = VALUES(`current`)",
        ("EMP-", max_used),
    )


class Employee(Document):
    def validate(self):
        self.employee_name = (self.employee_name or "").strip()
        self.department = (self.department or "").strip()
        if not self.employee_name or not self.department:
            frappe.throw(_("Employee Name and Department are required."))
        if self.status not in ("Active", "Inactive"):
            frappe.throw(_("Employee status must be Active or Inactive."))

    def on_trash(self):
        from frappe.model.delete_doc import check_if_doc_is_linked
        if check_if_doc_is_linked(self):
            frappe.throw(_("Employees with transaction history cannot be deleted. Set the employee status to Inactive to preserve historical records."))
