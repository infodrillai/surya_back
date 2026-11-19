import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class BondingLog(Document):
    def validate(self):
        if flt(self.bonding_output_kg) <= 0:
            frappe.throw(_("Bonding Output Quantity must be greater than zero."))
