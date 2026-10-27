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
        taxable = 0.0
        tot_ordered = tot_received = 0.0

        extra = max(0.0, flt(self.extra_charges))
        self.extra_charges = extra
        header_gst = max(0.0, flt(getattr(self, "gst_percent", 0.0)))
        self.gst_percent = header_gst

        for r in self.items:
            r.quantity = max(0.0, flt(r.quantity))
            r.rate = max(0.0, flt(r.rate))
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.amount = round(r.quantity * r.rate, 2)
            taxable += r.amount

            r.received_qty = max(0.0, flt(getattr(r, "received_qty", 0.0)))
            r.pending_qty = max(0.0, r.quantity - r.received_qty)
            tot_ordered += r.quantity
            tot_received += r.received_qty

        shares = allocate_extra([r.amount for r in self.items], extra)
        for r, share in zip(self.items, shares):
            r.landed_rate = round((r.amount + share) / flt(r.quantity), 4) if flt(r.quantity) else 0.0

        tax = 0.0
        if header_gst > 0:
            taxable_base = taxable + extra
            g = split_gst(taxable_base, header_gst, self.vendor_state, company_state)
            tax = round(g["cgst"] + g["sgst"] + g["igst"], 2)
            for r in self.items:
                r.gst_percent = header_gst
                gi = split_gst(r.amount, header_gst, self.vendor_state, company_state)
                r.cgst, r.sgst, r.igst = gi["cgst"], gi["sgst"], gi["igst"]
        else:
            for r in self.items:
                g = split_gst(r.amount, flt(r.gst_percent), self.vendor_state, company_state)
                r.cgst, r.sgst, r.igst = g["cgst"], g["sgst"], g["igst"]
                tax += g["cgst"] + g["sgst"] + g["igst"]
            tax = round(tax, 2)

        self.taxable_amount = round(taxable, 2)
        self.tax_amount = round(tax, 2)
        self.grand_total = round(taxable + extra + tax, 2)
        self.total_ordered_qty = round(tot_ordered, 4)
        self.total_received_qty = round(tot_received, 4)
        self.total_pending_qty = max(0.0, round(tot_ordered - tot_received, 4))

        # Check purchase limits and approval requirement
        threshold_exceeded = False
        exceeded_details = []

        global_limit = 0.0
        require_approval = 1
        if frappe.db.exists("DocType", "Purchase Setting"):
            try:
                ps = frappe.get_single("Purchase Setting")
                global_limit = flt(ps.get("max_purchase_qty"))
                require_approval = int(ps.get("require_approval") if ps.get("require_approval") is not None else 1)
            except Exception:
                pass

        if require_approval:
            for r in self.items:
                qty = flt(r.quantity)
                prod_doc = frappe.db.get_value("Product", r.product, ["max_purchase_qty", "category", "product_name"], as_dict=True)
                p_limit = flt(prod_doc.get("max_purchase_qty")) if prod_doc else 0.0
                c_limit = 0.0
                if prod_doc and prod_doc.get("category"):
                    c_limit = flt(frappe.db.get_value("Category", prod_doc.category, "max_purchase_qty"))

                limit = p_limit if p_limit > 0 else (c_limit if c_limit > 0 else global_limit)
                if limit > 0 and qty > limit:
                    threshold_exceeded = True
                    pname = (prod_doc and prod_doc.product_name) or r.product
                    exceeded_details.append(f"{pname}: ordered {qty}, limit {limit}")

        self.threshold_exceeded = int(bool(threshold_exceeded))

        if threshold_exceeded:
            if getattr(self, "approval_status", None) not in ("Approved", "Rejected"):
                self.approval_status = "Pending"
                self.status = "Pending Approval"
        else:
            if not getattr(self, "approval_status", None) or self.approval_status == "Pending":
                self.approval_status = "Not Required"
            if not getattr(self, "status", None) or self.status == "Pending Approval":
                self.status = "Draft"

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

        # Re-check threshold if status was somehow modified directly
        if self.threshold_exceeded and self.approval_status == "Pending" and self.status not in ("Pending Approval", "Draft"):
            self.status = "Pending Approval"

    def stock_entries(self):
        # Stock is posted only when Goods Receipt is confirmed.
        return []

    # -----------------------------------------------------------------
    # Whitelisted UI actions & Approvals
    # -----------------------------------------------------------------
    @frappe.whitelist()
    def confirm_order(self):
        self.check_permission("write")
        if self.threshold_exceeded and self.approval_status == "Pending":
            frappe.throw(
                _("Purchase Order {0} exceeds the permitted purchase quantity threshold and is Pending Approval. It must be approved before order confirmation.")
                .format(self.name),
                title=_("Approval Required")
            )
        if self.approval_status == "Rejected" or self.status == "Rejected":
            frappe.throw(
                _("Cannot confirm rejected Purchase Order {0}.").format(self.name),
                title=_("Order Rejected")
            )
        if self.status not in ("Draft", "Approved"):
            frappe.throw(
                _("Only Draft or Approved purchase orders can be marked as Ordered. Current status: {0}.").format(self.status)
            )

        self.db_set({"status": "Ordered"})
        return {"name": self.name, "status": "Ordered"}

    @frappe.whitelist()
    def approve_purchase(self):
        user_roles = set(frappe.get_roles(frappe.session.user))
        if not (user_roles & {"CS Admin", "System Manager", "Administrator"}):
            frappe.throw(_("Only CS Admin or System Manager can approve purchases above the threshold."), frappe.PermissionError)

        self.db_set({
            "approval_status": "Approved",
            "approved_by": frappe.session.user,
            "approved_on": now_datetime(),
            "status": "Approved",
        })
        frappe.msgprint(_("Purchase Order {0} approved.").format(self.name))
        return {"name": self.name, "status": "Approved", "approval_status": "Approved"}

    @frappe.whitelist()
    def reject_purchase(self, reason=None):
        user_roles = set(frappe.get_roles(frappe.session.user))
        if not (user_roles & {"CS Admin", "System Manager", "Administrator"}):
            frappe.throw(_("Only CS Admin or System Manager can reject purchases."), frappe.PermissionError)

        if not reason or not str(reason).strip():
            frappe.throw(_("A reason is mandatory when rejecting a purchase order."))

        self.db_set({
            "approval_status": "Rejected",
            "rejection_reason": str(reason).strip(),
            "status": "Rejected",
        })
        frappe.msgprint(_("Purchase Order {0} rejected.").format(self.name))
        return {"name": self.name, "status": "Rejected", "approval_status": "Rejected"}

    @frappe.whitelist()
    def cancel_order(self):
        self.check_permission("write")
        if self.status in ("Received", "Cancelled"):
            frappe.throw(_("Purchase Order {0} is already {1} and cannot be cancelled.").format(self.name, self.status))

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
            "approval_status": getattr(self, "approval_status", "Not Required"),
            "threshold_exceeded": getattr(self, "threshold_exceeded", 0),
            "total_ordered_qty": flt(self.total_ordered_qty),
            "total_received_qty": flt(self.total_received_qty),
            "total_pending_qty": flt(self.total_pending_qty),
            "items": items,
        }
