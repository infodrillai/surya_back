import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from clssurya.utils.base import CompletableDocument
from clssurya.utils.costing import allocate_extra, split_gst

EPS = 1e-6

class PurchaseEntry(CompletableDocument):
    def calculate(self):
        self.vendor_state = frappe.db.get_value("Vendor", self.vendor, "state") or ""
        company_state = frappe.conf.get("company_state") or "Gujarat"
        taxable = tax = 0.0
        tot_ordered = tot_received = 0.0

        for r in self.items:
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.amount = flt(r.quantity) * flt(r.rate)
            g = split_gst(r.amount, flt(r.gst_percent), self.vendor_state, company_state)
            r.cgst, r.sgst, r.igst = g["cgst"], g["sgst"], g["igst"]
            taxable += r.amount
            tax += g["cgst"] + g["sgst"] + g["igst"]

            r.received_qty = flt(getattr(r, "received_qty", 0.0))
            r.pending_qty = max(0.0, flt(r.quantity) - r.received_qty)
            tot_ordered += flt(r.quantity)
            tot_received += r.received_qty

        shares = allocate_extra([r.amount for r in self.items], flt(self.extra_charges))
        for r, share in zip(self.items, shares):
            r.landed_rate = (r.amount + share) / flt(r.quantity) if flt(r.quantity) else 0

        self.taxable_amount, self.tax_amount = taxable, tax
        self.grand_total = taxable + tax + flt(self.extra_charges)
        self.total_ordered_qty = tot_ordered
        self.total_received_qty = tot_received
        self.total_pending_qty = max(0.0, tot_ordered - tot_received)

        if not getattr(self, "status", None):
            self.status = "Draft"

    def validate_doc(self):
        if not self.items:
            frappe.throw(_("Add at least one item."))
        for r in self.items:
            if frappe.db.get_value("Product", r.product, "product_type") != "Raw":
                frappe.throw(_("{0} is not a Raw product.").format(r.product))
            if flt(r.quantity) <= 0 or flt(r.rate) < 0:
                frappe.throw(_("Row {0}: quantity must be above 0 and rate cannot be negative.").format(r.idx))

    def stock_entries(self):
        # Purchase Order does NOT add stock to Inventory directly.
        # Stock is added only when Goods Receipt is confirmed.
        return []

    # -----------------------------------------------------------------
    # Whitelisted UI actions
    # -----------------------------------------------------------------
    @frappe.whitelist()
    def confirm_order(self):
        self.check_permission("write")
        if self.status != "Draft":
            frappe.throw(_("Only Draft purchase orders can be marked as Ordered. Current status: {0}.").format(self.status))
        self.db_set({
            "status": "Ordered",
        })
        return {"name": self.name, "status": "Ordered"}

    @frappe.whitelist()
    def cancel_order(self):
        self.check_permission("write")
        if self.status in ("Received", "Cancelled"):
            frappe.throw(_("Purchase Order {0} is already {1} and cannot be cancelled.").format(self.name, self.status))

        # Check if any confirmed goods receipts exist
        confirmed = frappe.get_all(
            "Goods Receipt",
            filters={"purchase_order": self.name, "status": "Confirmed"},
            pluck="name",
        )
        if confirmed:
            frappe.throw(
                _("Cannot cancel Purchase Order {0}: confirmed Goods Receipts exist ({1}). Cancel them first.")
                .format(self.name, ", ".join(confirmed))
            )

        self.db_set({
            "status": "Cancelled",
            "is_completed": 0,
        })
        return {"name": self.name, "status": "Cancelled"}

    @frappe.whitelist()
    def get_pending_items(self):
        """Helper for Goods Receipt dialog."""
        confirmed_grs = frappe.get_all(
            "Goods Receipt",
            filters={"purchase_order": self.name, "status": "Confirmed"},
            pluck="name",
        )
        already_received_map = {}
        for gr_name in confirmed_grs:
            for row in frappe.get_doc("Goods Receipt", gr_name).items:
                already_received_map[row.purchase_order_item] = already_received_map.get(row.purchase_order_item, 0.0) + flt(row.received_qty)

        items = []
        for line in self.items:
            ordered = flt(line.quantity)
            already_rcv = already_received_map.get(line.name, flt(getattr(line, "received_qty", 0.0)))
            pending = max(0.0, ordered - already_rcv)
            items.append({
                "purchase_order_item": line.name,
                "product": line.product,
                "product_name": frappe.db.get_value("Product", line.product, "product_name") or line.product,
                "uom": line.uom or frappe.db.get_value("Product", line.product, "uom"),
                "ordered_qty": ordered,
                "already_received_qty": already_rcv,
                "pending_qty": pending,
                "rate": flt(line.rate),
                "landed_rate": flt(line.landed_rate) if flt(line.landed_rate) else flt(line.rate),
            })

        return {
            "name": self.name,
            "vendor": self.vendor,
            "posting_date": self.posting_date,
            "expected_delivery_date": getattr(self, "expected_delivery_date", None),
            "status": self.status,
            "total_ordered_qty": flt(self.total_ordered_qty),
            "total_received_qty": flt(self.total_received_qty),
            "total_pending_qty": flt(self.total_pending_qty),
            "items": items,
        }
