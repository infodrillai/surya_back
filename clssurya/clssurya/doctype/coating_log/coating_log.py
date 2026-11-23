import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class CoatingLog(Document):
    def validate(self):
        hub = flt(self.hub_1046m_kg)
        cl = flt(self.cl_501_kg)
        tolnue = flt(self.tolnue_kg)
        self.coating_total_kg = hub + cl + tolnue

        if flt(self.roll_meters_coated) <= 0:
            frappe.throw(_("Roll Meters Coated must be greater than zero."))
        input_qty, good, rejected = flt(self.input_qty), flt(self.good_qty), flt(self.rejected_qty)
        if min(input_qty, good, rejected, flt(self.pending_qty)) < 0:
            frappe.throw(_("Production quantities cannot be negative."))
        if rejected and not input_qty:
            frappe.throw(_("Input Quantity is required when recording rejected production."))
        if input_qty and good == 0:
            good = min(flt(self.roll_meters_coated), max(0, input_qty - rejected))
            self.good_qty = good
        if input_qty and good + rejected > input_qty:
            frappe.throw(_("Good plus Rejected quantity cannot exceed Input Quantity."))
        if input_qty:
            self.pending_qty = input_qty - good - rejected
