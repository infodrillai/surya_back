import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class ExternalGrindingLog(Document):
    def validate(self):
        sent = flt(self.sent_qty)
        accepted = flt(self.accepted_qty)
        rejected = flt(self.rejected_qty)

        if sent <= 0:
            frappe.throw(_("Sent Quantity must be greater than zero."))
        if accepted < 0 or rejected < 0:
            frappe.throw(_("Accepted and Rejected quantities cannot be negative."))

        if not flt(self.returned_qty):
            self.returned_qty = accepted + rejected

        returned = flt(self.returned_qty)
        if returned > sent:
            frappe.throw(_("Returned quantity ({0}) cannot exceed Sent quantity ({1}).").format(returned, sent))

        self.pending_qty = max(0.0, sent - returned)

        if self.pending_qty == 0 and returned > 0:
            self.grinding_status = "Completed"
        elif returned > 0 and self.pending_qty > 0:
            self.grinding_status = "Partially Received"
        elif returned == 0:
            self.grinding_status = "Dispatched"
