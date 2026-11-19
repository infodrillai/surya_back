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

        if not flt(self.qty_processed):
            self.qty_processed = flt(self.accepted_qty) + flt(self.rejected_qty)

        if flt(self.input_qty) > 0:
            self.pending_qty = max(0.0, flt(self.input_qty) - (flt(self.accepted_qty) + flt(self.rejected_qty)))

        if self.product and not self.product_name:
            self.product_name = frappe.db.get_value("Product", self.product, "product_name") or self.product
