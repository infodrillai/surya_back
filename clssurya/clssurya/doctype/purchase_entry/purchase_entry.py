import frappe
from frappe import _
from frappe.utils import flt

from clssurya.utils.base import CompletableDocument
from clssurya.utils.costing import allocate_extra, split_gst


class PurchaseEntry(CompletableDocument):
    def calculate(self):
        self.vendor_state = frappe.db.get_value("Vendor", self.vendor, "state") or ""
        company_state = frappe.conf.get("company_state") or "Gujarat"
        taxable = tax = 0.0
        for r in self.items:
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.amount = flt(r.quantity) * flt(r.rate)
            g = split_gst(r.amount, flt(r.gst_percent), self.vendor_state, company_state)
            r.cgst, r.sgst, r.igst = g["cgst"], g["sgst"], g["igst"]
            taxable += r.amount
            tax += g["cgst"] + g["sgst"] + g["igst"]
        shares = allocate_extra([r.amount for r in self.items], flt(self.extra_charges))
        for r, share in zip(self.items, shares):
            r.landed_rate = (r.amount + share) / flt(r.quantity) if flt(r.quantity) else 0
        self.taxable_amount, self.tax_amount = taxable, tax
        self.grand_total = taxable + tax + flt(self.extra_charges)

    def validate_doc(self):
        if not self.items:
            frappe.throw(_("Add at least one item."))
        for r in self.items:
            if frappe.db.get_value("Product", r.product, "product_type") != "Raw":
                frappe.throw(_("{0} is not a Raw product.").format(r.product))
            if flt(r.quantity) <= 0 or flt(r.rate) < 0:
                frappe.throw(_("Row {0}: quantity must be above 0 and rate cannot be negative.").format(r.idx))

    def stock_entries(self):
        return [{"product": r.product, "stage": "Raw", "qty": flt(r.quantity), "unit_price": flt(r.landed_rate)} for r in self.items]
