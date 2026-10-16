import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class Product(Document):
    def validate(self):
        if self.product_type == "Raw":
            self.total_steps = 0
        elif cint(self.total_steps) not in (1, 2, 3):
            frappe.throw(_("Total steps must be 1, 2 or 3 for Semi / Finished products."))
        if flt(self.high_stock_limit) and flt(self.high_stock_limit) < flt(self.low_stock_limit):
            frappe.throw(_("High stock limit cannot be below the low stock limit."))
