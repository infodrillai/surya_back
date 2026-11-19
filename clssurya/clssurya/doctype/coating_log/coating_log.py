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
