import frappe
from frappe.utils import nowdate
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from clssurya.utils.stock_service import inventory_price
from clssurya.utils.base import require_admin

class SalesOrder(Document):
    # -----------------------------------------------------------------
    #  Validation / lifecycle helpers
    # -----------------------------------------------------------------
    def validate(self):
        before = self.get_doc_before_save()
        if before and before.status != "Pending Approval":
            frappe.throw(_("Only orders pending approval can be edited."))
        self.status = "Pending Approval"
        if not self.items:
            frappe.throw(_("Add at least one item."))

        is_new = not before
        subtotal, below = 0.0, 0
        for r in self.items:
            r.uom = frappe.db.get_value("Product", r.product, "uom")
            r.amount = flt(r.quantity) * flt(r.rate)
            # initialise dispatch tracking only on a brand-new doc
            if is_new:
                r.dispatched_qty = 0
                r.returned_qty = 0
                r.net_delivered_qty = 0
                r.pending_qty = flt(r.quantity)
            below = below or (flt(r.rate) < inventory_price(r.product, "Finished"))
            subtotal += r.amount

        discount_percent = flt(self.discount_percent or 0)
        discount_amount = subtotal * discount_percent / 100
        taxable_amount = max(0.0, subtotal - discount_amount)
        gst_percent = flt(self.gst_percent or 0)
        tax_amount = taxable_amount * gst_percent / 100
        grand_total = taxable_amount + tax_amount

        self.subtotal = subtotal
        self.total_amount = subtotal           # kept for legacy compatibility
        self.discount_amount = discount_amount
        self.taxable_amount = taxable_amount
        self.tax_amount = tax_amount
        self.grand_total = grand_total
        self.below_cost = 1 if below else 0

    def on_trash(self):
        if self.status != "Pending Approval":
            frappe.throw(_("Only orders pending approval can be deleted."))

    # -----------------------------------------------------------------
    #  Core actions (whitelisted)
    # -----------------------------------------------------------------
    @frappe.whitelist()
    def approve(self):
        require_admin()
        if self.status != "Pending Approval":
            frappe.throw(_("Order is already {0}.").format(self.status))
        self.db_set({
            "status": "Approved",
            "approved_by": frappe.session.user,
            "approved_on": now_datetime(),
        })
        return self.name

    @frappe.whitelist()
    def reject(self):
        require_admin()
        if self.status in ("Completed", "Cancelled", "Rejected"):
            frappe.throw(_("Only pending or approved orders can be rejected."))
        self.db_set({
            "status": "Rejected",
            "cancelled_by": frappe.session.user,
            "cancelled_on": now_datetime(),
        })
        return self.name

    @frappe.whitelist()
    def cancel(self):
        require_admin()
        if self.status in ("Completed", "Cancelled"):
            frappe.throw(_("Only pending or approved orders can be cancelled."))
        # block cancel if a **dispatched** (confirmed) dispatch exists
        linked = frappe.get_all(
            "Dispatch",
            filters={"sales_order": self.name, "dispatch_status": "Dispatched"},
            fields=["name"],
        )
        if linked:
            frappe.throw(_("Cannot cancel – a confirmed dispatch exists."))
        self.db_set({
            "status": "Cancelled",
            "cancelled_by": frappe.session.user,
            "cancelled_on": now_datetime(),
        })
        return self.name

    # -----------------------------------------------------------------
    #  Helper to collect pending items (used by UI)
    # -----------------------------------------------------------------
    def get_pending_items(self):
        """Return a list of items that still have quantity left to dispatch."""
        pending = []
        for item in self.items:
            pending_qty = flt(item.quantity) - flt(item.dispatched_qty)
            if pending_qty > 0:
                pending.append({
                    "order_item": item.name,
                    "product": item.product,
                    "ordered_qty": flt(item.quantity),
                    "already_dispatched": flt(item.dispatched_qty),
                    "pending_qty": pending_qty,
                })
        return pending

    @frappe.whitelist()
    def create_dispatch(self):
        """
        UI helper – returns pending items for the QtyDialog.
        Does **not** create a Dispatch.
        """
        pending = self.get_pending_items()
        return {"pending_items": pending}

    # -----------------------------------------------------------------
    #  NEW: create a **Draft** Dispatch from a Sales Order
    # -----------------------------------------------------------------
    @frappe.whitelist()
    def create_dispatch_from_sales_order(self, items):
        """
        items = [{order_item: <str>, quantity: <number>}]
        Creates a Dispatch with dispatch_status = "Draft" that contains only
        rows where quantity > 0.  No Sales Order status change here.
        """
        require_admin()
        if self.status not in ("Approved", "Partially Dispatched"):
            frappe.throw(_("Sales Order must be Approved or Partially Dispatched."))

        # Parse items argument (may arrive as a JSON string)
        if isinstance(items, str):
            items = frappe.parse_json(items)

        # Build a map of requested quantities (only > 0)
        qty_map = {i["order_item"]: flt(i["quantity"]) for i in items if flt(i["quantity"]) > 0}

        if not qty_map:
            frappe.throw(_("No dispatch quantities supplied."))

        # ── Lock the SO row to prevent concurrent submissions ──────────
        frappe.db.sql(
            "SELECT name FROM `tabSales Order` WHERE name=%s FOR UPDATE",
            (self.name,),
        )
        self.reload()  # refresh after lock in case another worker just confirmed something

        # Quantities already confirmed (Dispatched) dispatches occupy
        confirmed_dispatched = {}  # order_item -> total already confirmed
        conf_dispatches = frappe.get_all(
            "Dispatch",
            filters={"sales_order": self.name, "dispatch_status": "Dispatched"},
            pluck="name",
        )
        for dname in conf_dispatches:
            for row in frappe.get_doc("Dispatch", dname).items:
                confirmed_dispatched.setdefault(row.order_item, 0.0)
                confirmed_dispatched[row.order_item] += flt(row.quantity)

        # Quantities already reserved in *Draft* dispatches (not yet confirmed)
        reserved = {}
        draft_dispatches = frappe.get_all(
            "Dispatch",
            filters={"sales_order": self.name, "dispatch_status": "Draft"},
            pluck="name",
        )
        for dname in draft_dispatches:
            for row in frappe.get_doc("Dispatch", dname).items:
                reserved.setdefault(row.order_item, 0.0)
                reserved[row.order_item] += flt(row.quantity)

        for item in self.items:
            if item.name not in qty_map:
                continue
            ordered = flt(item.quantity)
            already_confirmed = confirmed_dispatched.get(item.name, 0.0)
            already_reserved = reserved.get(item.name, 0.0)
            available = max(0.0, ordered - already_confirmed - already_reserved)
            requested = qty_map[item.name]
            if requested > available + 1e-6:
                pname = (
                    frappe.db.get_value("Product", item.product, "product_name")
                    or item.product
                )
                frappe.throw(
                    _("{0}: requested {1} exceeds available pending qty {2} (ordered {3} − confirmed {4} − draft-reserved {5}).")
                    .format(pname, flt(requested, 4), flt(available, 4),
                            flt(ordered, 4), flt(already_confirmed, 4), flt(already_reserved, 4))
                )

        # ── Create the Dispatch document (dispatch_status = Draft) ──────
        disp = frappe.new_doc("Dispatch")
        disp.sales_order = self.name
        disp.customer = self.customer
        disp.dispatch_date = nowdate()
        disp.dispatch_status = "Draft"  # explicit; also the field default

        for item in self.items:
            if item.name not in qty_map:
                continue
            qty = qty_map[item.name]
            disp.append(
                "items",
                {
                    "order_item": item.name,
                    "product": item.product,
                    "ordered_qty": flt(item.quantity),
                    "already_dispatched": flt(item.dispatched_qty),
                    "quantity": qty,
                    "unit_cost": flt(item.rate),
                },
            )

        disp.flags.ignore_validate = True  # skip CompletableDocument validate on insert
        disp.insert(ignore_permissions=False)
        return {"name": disp.name, "dispatch_status": disp.dispatch_status}

    # -----------------------------------------------------------------
    #  Helper used by the UI to know whether a Sales Order already has a
    #  confirmed Dispatch (needed to block cancellation)
    # -----------------------------------------------------------------
    @frappe.whitelist()
    def linked_dispatches(self):
        """Return a list of dispatches linked to this Sales Order."""
        return frappe.get_all(
            "Dispatch",
            filters={"sales_order": self.name},
            fields=["name", "dispatch_status"],
        )
