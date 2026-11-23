import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class BondingLog(Document):
    def validate(self):
        if flt(self.bonding_output_kg) <= 0:
            frappe.throw(_("Bonding Output Quantity must be greater than zero."))
        self.validate_quantities()

    def validate_quantities(self):
        input_qty, good, rejected = flt(self.input_qty), flt(self.good_qty), flt(self.rejected_qty)
        if min(input_qty, good, rejected, flt(self.pending_qty)) < 0:
            frappe.throw(_("Production quantities cannot be negative."))
        if rejected and not input_qty:
            frappe.throw(_("Input Quantity is required when recording rejected production."))
        if input_qty and good == 0:
            good = min(flt(self.bonding_output_kg), max(0, input_qty - rejected))
            self.good_qty = good
        if input_qty and good + rejected > input_qty:
            frappe.throw(_("Good plus Rejected quantity cannot exceed Input Quantity."))
        if input_qty:
            self.pending_qty = input_qty - good - rejected
