import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from clssurya.utils.stock_service import inventory_price


class Quotation(Document):
    def validate(self):
        before = self.get_doc_before_save()
        if before and before.status in ("Superseded", "Accepted"):
            frappe.throw(_("A {0} quotation cannot be edited. Revise it instead.").format(before.status))
        if self.status == "Superseded" and not (before and before.status == "Superseded"):
            frappe.throw(_("Status becomes Superseded automatically when you revise."))
        if not self.items:
            frappe.throw(_("Add at least one item."))
        total, below = 0.0, 0
        for r in self.items:
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.production_cost = inventory_price(r.product, "Finished")
            r.amount = flt(r.quantity) * flt(r.rate)
            r.below_cost = 1 if flt(r.rate) < flt(r.production_cost) else 0
            below = below or r.below_cost
            total += r.amount
        self.total_amount, self.below_cost = total, below

    def on_trash(self):
        if self.status == "Accepted":
            frappe.throw(_("An accepted quotation cannot be deleted."))

    def revise(self):
        if self.status == "Superseded":
            frappe.throw(_("Already superseded."))
        new = frappe.copy_doc(self)
        new.version = cint(self.version) + 1
        new.parent_quotation = self.name
        new.status = "Draft"
        new.insert()
        self.db_set("status", "Superseded")
        return new.name

    def make_sales_order(self):
        if self.status == "Superseded":
            frappe.throw(_("Create the order from the latest version."))
        so = frappe.get_doc({
            "doctype": "Sales Order", "customer": self.customer, "order_date": frappe.utils.today(), "quotation": self.name,
            "items": [{"product": r.product, "quantity": r.quantity, "rate": r.rate} for r in self.items],
        }).insert()
        self.db_set("status", "Accepted")
        return so.name

    def approve(self):
        """Approve a quotation – changes status to Approved.
        Only Draft quotations can be approved; otherwise a validation error is raised.
        """
        if self.status != "Draft":
            frappe.throw(_("Only Draft quotations can be approved."))
        # Update status and persist
        self.db_set("status", "Approved")
        return f"Quotation {self.name} approved"

