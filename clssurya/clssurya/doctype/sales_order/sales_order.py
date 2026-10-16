import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from clssurya.utils.base import require_admin
from clssurya.utils.stock_service import inventory_price


class SalesOrder(Document):
    def validate(self):
        before = self.get_doc_before_save()
        if before and before.status != "Pending Approval":
            frappe.throw(_("Only orders pending approval can be edited."))
        self.status = "Pending Approval"
        if not self.items:
            frappe.throw(_("Add at least one item."))
        total, below = 0.0, 0
        for r in self.items:
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.amount = flt(r.quantity) * flt(r.rate)
            r.dispatched_qty = 0
            r.pending_qty = flt(r.quantity)
            below = below or (flt(r.rate) < inventory_price(r.product, "Finished"))
            total += r.amount
        self.total_amount, self.below_cost = total, 1 if below else 0

    def on_trash(self):
        if self.status != "Pending Approval":
            frappe.throw(_("Only orders pending approval can be deleted."))

    def approve(self):
        require_admin()
        if self.status != "Pending Approval":
            frappe.throw(_("Order is already {0}.").format(self.status))
        self.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
        return self.name
