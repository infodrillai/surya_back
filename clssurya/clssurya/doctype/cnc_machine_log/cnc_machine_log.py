import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class CNCMachineLog(Document):
    def validate(self):
        if flt(self.input_qty) < 0:
            frappe.throw(_("Input Quantity cannot be negative."))
        if flt(self.accepted_qty) < 0:
            frappe.throw(_("Accepted Quantity cannot be negative."))
        if flt(self.rejected_qty) < 0:
            frappe.throw(_("Rejected Quantity cannot be negative."))
        if flt(self.pending_qty) < 0:
            frappe.throw(_("Pending Quantity cannot be negative."))
        input_qty = flt(self.input_qty)
        accepted = flt(self.accepted_qty)
        rejected = flt(self.rejected_qty)
        if input_qty and accepted + rejected > input_qty:
            frappe.throw(_("Accepted plus Rejected quantity cannot exceed Input Quantity."))
        if input_qty:
            self.pending_qty = input_qty - accepted - rejected
        if not flt(self.qty_processed):
            self.qty_processed = accepted + rejected

        if self.product and not self.product_name:
            self.product_name = frappe.db.get_value("Product", self.product, "product_name") or self.product
