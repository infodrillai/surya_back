import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, today

from clssurya.utils.stock_service import inventory_price
from clssurya.utils.quotation_versions import get_family_root, get_latest_version


EPS = 1e-6


class Quotation(Document):
    def validate(self):
        before = self.get_doc_before_save()

        if before and before.status in ("Superseded", "Accepted"):
            frappe.throw(
                _("A {0} quotation cannot be edited. Revise it instead.")
                .format(before.status)
            )

        if self.status == "Superseded" and not (
            before and before.status == "Superseded"
        ):
            frappe.throw(_("Status becomes Superseded automatically when you revise."))

        if not self.items:
            frappe.throw(_("Add at least one item."))

        discount_percent = flt(self.discount_percent)
        gst_percent = flt(self.gst_percent)

        if not 0 <= discount_percent <= 100:
            frappe.throw(_("Discount must be between 0 and 100%."))

        if not 0 <= gst_percent <= 100:
            frappe.throw(_("GST must be between 0 and 100%."))

        subtotal = 0.0
        below_cost = 0

        for row in self.items:
            if flt(row.quantity) <= 0:
                frappe.throw(_("Row {0}: quantity must be greater than zero.").format(row.idx))

            row.uom = frappe.db.get_value("Product", row.product, "uom")
            row.production_cost = inventory_price(row.product, "Finished")

            # Keep the rate supplied by the quotation form.
            row.amount = flt(row.quantity) * flt(row.rate)
            row.below_cost = int(flt(row.rate) < flt(row.production_cost))
            below_cost = below_cost or row.below_cost
            subtotal += flt(row.amount)

        discount_amount = subtotal * discount_percent / 100
        taxable_amount = max(0, subtotal - discount_amount)
        tax_amount = taxable_amount * gst_percent / 100
        grand_total = taxable_amount + tax_amount

        self.subtotal = subtotal
        self.total_amount = subtotal  # compatibility with existing screens
        self.discount_amount = discount_amount
        self.taxable_amount = taxable_amount
        self.tax_amount = tax_amount
        self.grand_total = grand_total
        self.below_cost = int(bool(below_cost))

    def on_trash(self):
        if self.status == "Accepted":
            frappe.throw(_("An accepted quotation cannot be deleted."))

        if frappe.db.exists("Sales Order", {"quotation": self.name}):
            frappe.throw(_("This quotation is linked to a Sales Order and cannot be deleted."))

        if frappe.db.exists("Quotation", {"previous_version": self.name}):
            frappe.throw(_("This quotation has a later revision and cannot be deleted."))

    # @frappe.whitelist()
    # def revise(self):
    #     if self.status in ("Superseded", "Accepted"):
    #         frappe.throw(_("This quotation cannot be revised from its current status."))

    #     # Lock the source quotation so two requests cannot create the same revision.
    #     frappe.db.sql(
    #         "SELECT name FROM `tabQuotation` WHERE name=%s FOR UPDATE",
    #         (self.name,),
    #     )
    #     self.reload()

    #     if self.status in ("Superseded", "Accepted"):
    #         frappe.throw(_("This quotation has already been revised or accepted."))

    #     existing = frappe.db.exists(
    #         "Quotation",
    #         {"previous_version": self.name},
    #     )
    #     if existing:
    #         frappe.throw(_("Revision {0} already exists.").format(existing))

    #     new_doc = frappe.copy_doc(self)
    #     new_doc.name = None
    #     new_doc.version = cint(self.version or 1) + 1
    #     new_doc.previous_version = self.name
    #     new_doc.parent_quotation = self.parent_quotation or self.name
    #     new_doc.status = "Draft"

    #     # Recalculate all totals on the new document when it is inserted.
    #     new_doc.insert()

    #     self.db_set("status", "Superseded")
    #     return new_doc.name
    @frappe.whitelist()
    def revise(self):
        if self.status in ("Superseded", "Accepted"):
            frappe.throw(_("This quotation cannot be revised from its current status."))

        # Lock the source row so two requests cannot create the same revision.
        frappe.db.sql("SELECT name FROM `tabQuotation` WHERE name=%s FOR UPDATE", (self.name,))
        self.reload()

        if self.status in ("Superseded", "Accepted"):
            frappe.throw(_("This quotation has already been revised or accepted."))

        existing = frappe.db.exists("Quotation", {"previous_version": self.name})
        if existing:
            frappe.throw(_("Revision {0} already exists.").format(existing))

        current_version = cint(self.version or 1)
        if current_version < get_latest_version(self.name):
            frappe.throw(_("Only the latest version of a quotation can be revised."))

        new_doc = frappe.copy_doc(self)
        new_doc.name = None
        new_doc.version = current_version + 1
        new_doc.previous_version = self.name
        new_doc.parent_quotation = get_family_root(self.name)  # always the first version
        new_doc.status = "Draft"
        new_doc.insert()  # validate() recalculates totals from the copied rows

        self.db_set("status", "Superseded")
        return new_doc.name

    @frappe.whitelist()
    def approve(self):
        if self.status != "Draft":
            frappe.throw(_("Only Draft quotations can be approved."))

        self.db_set("status", "Approved")
        return self.name
    
    @frappe.whitelist()
    def make_sales_order(self):
        if self.status != "Approved":
            frappe.throw(_("Only an approved quotation can create a Sales Order."))

        if frappe.db.exists("Sales Order", {"quotation": self.name}):
            frappe.throw(_("A Sales Order already exists for quotation {0}.").format(self.name))

        # Refresh saved values and use server-calculated totals.
        self.reload()

        sales_order = frappe.get_doc({
            "doctype": "Sales Order",
            "customer": self.customer,
            "order_date": today(),
            "quotation": self.name,
            "subtotal": flt(self.subtotal or self.total_amount),
            "discount_percent": flt(self.discount_percent),
            "discount_amount": flt(self.discount_amount),
            "taxable_amount": flt(self.taxable_amount),
            "gst_percent": flt(self.gst_percent),
            "tax_amount": flt(self.tax_amount),
            "grand_total": flt(self.grand_total),
            "total_amount": flt(self.grand_total),
            "items": [
                {
                    "product": row.product,
                    "quantity": row.quantity,
                    "rate": row.rate,
                }
                for row in self.items
            ],
        })
        sales_order.insert()

        self.db_set("status", "Accepted")
        return sales_order.name
