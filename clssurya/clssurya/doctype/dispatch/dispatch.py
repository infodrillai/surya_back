import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate
from clssurya.utils.base import CompletableDocument
from clssurya.utils.stock_service import inventory_price, post as stock_post, reverse as stock_reverse

EPS = 1e-6  # tolerance for floating-point comparisons


class Dispatch(CompletableDocument):
    """
    Lifecycle:
      insert()              → dispatch_status = 'Draft'   (no stock effect)
      confirm_dispatch()    → dispatch_status = 'Dispatched'  (deducts Finished stock once, updates SO)
      cancel_dispatch()     → dispatch_status = 'Cancelled'
          - Draft   → just mark Cancelled, no stock change
          - Dispatched → reverse stock and restore SO dispatched quantities (admin only)
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _order(self, lock=False):
        if not self.sales_order:
            frappe.throw(_("Select a sales order."))
        if lock:
            frappe.db.sql(
                "SELECT name FROM `tabSales Order` WHERE name=%s FOR UPDATE",
                (self.sales_order,),
            )
        return frappe.get_doc("Sales Order", self.sales_order)

    def _refresh_item_info(self):
        """Sync product/ordered_qty/already_dispatched from the SO and set unit_cost."""
        so = self._order()
        lines = {r.name: r for r in so.items}
        for r in self.items:
            line = lines.get(r.order_item)
            if not line:
                frappe.throw(_("Row {0}: order line {1} not found.").format(r.idx, r.order_item))
            r.product = line.product
            r.ordered_qty = flt(line.quantity)
            r.already_dispatched = flt(line.dispatched_qty)
            r.unit_cost = inventory_price(r.product, "Finished")

    def _calc_grand_total(self):
        """
        Calculate grand_total for this Dispatch by summing:
          quantity * unit_cost  for each dispatch item (before tax/discount).
        We use the rate from the Sales Order items for accuracy.
        """
        so = self._order()
        so_items = {r.name: r for r in so.items}

        # Determine SO-level discount and GST
        discount_percent = flt(getattr(so, 'discount_percent', 0))
        gst_percent = flt(getattr(so, 'gst_percent', 18))

        subtotal = 0.0
        for r in self.items:
            so_line = so_items.get(r.order_item)
            rate = flt(so_line.rate) if so_line else flt(r.unit_cost)
            subtotal += flt(r.quantity) * rate

        discount_amount = subtotal * discount_percent / 100
        taxable_amount = max(0.0, subtotal - discount_amount)
        tax_amount = taxable_amount * gst_percent / 100
        grand_total = taxable_amount + tax_amount
        self.db_set('grand_total', grand_total, update_modified=False)

    def _validate_quantities(self):
        """Ensure each dispatch line qty > 0 and ≤ remaining."""
        for r in self.items:
            qty = flt(r.quantity)
            remaining = flt(r.ordered_qty) - flt(r.already_dispatched)
            if qty <= 0:
                frappe.throw(_("Row {0}: quantity must be greater than 0.").format(r.idx))
            if qty > remaining + EPS:
                frappe.throw(
                    _("Row {0}: cannot dispatch {1}; only {2} remaining.").format(
                        r.idx, flt(qty, 4), flt(remaining, 4)
                    )
                )

    def _check_stock(self):
        """Raise if Finished stock is insufficient for any dispatch line."""
        for r in self.items:
            qty = flt(r.quantity)
            available = flt(
                frappe.db.get_value(
                    "Inventory",
                    {"product": r.product, "stage": "Finished"},
                    "stock",
                )
                or 0
            )
            if qty > available + EPS:
                pname = (
                    frappe.db.get_value("Product", r.product, "product_name") or r.product
                )
                frappe.throw(
                    _("Insufficient Finished stock for {0}: available {1}, needed {2}.").format(
                        pname, flt(available, 4), flt(qty, 4)
                    ),
                    title=_("Insufficient Stock"),
                )

    def _apply_so_update(self, sign):
        """
        Update dispatched_qty and pending_qty on each linked SO item and set
        the Sales Order status (Approved / Partially Dispatched / Completed).

        sign = +1 when confirming, -1 when reversing.
        """
        so = self._order()
        for r in self.items:
            line = next((l for l in so.items if l.name == r.order_item), None)
            if not line:
                continue
            new_dispatched = max(0.0, flt(line.dispatched_qty) + sign * flt(r.quantity))
            frappe.db.set_value(
                "Sales Order Item",
                line.name,
                {
                    "dispatched_qty": new_dispatched,
                    "pending_qty": flt(line.quantity) - new_dispatched,
                },
            )
        so.reload()
        all_done = all(flt(l.dispatched_qty) >= flt(l.quantity) - EPS for l in so.items)
        any_done = any(flt(l.dispatched_qty) > EPS for l in so.items)
        if all_done:
            so_status = "Completed"
            flag = {
                "is_completed": 1,
                "completed_on": now_datetime(),
                "completed_by": frappe.session.user,
            }
        elif any_done:
            so_status = "Partially Dispatched"
            flag = {"is_completed": 0, "completed_on": None, "completed_by": None}
        else:
            so_status = "Approved"
            flag = {"is_completed": 0, "completed_on": None, "completed_by": None}
        so.db_set({"status": so_status, **flag})

    # ------------------------------------------------------------------
    # CompletableDocument hooks (used if someone calls .complete() directly)
    # ------------------------------------------------------------------

    def calculate(self):
        self._refresh_item_info()

    def validate_doc(self):
        if self._order().status not in ("Approved", "Partially Dispatched"):
            frappe.throw(_("The linked Sales Order must be Approved or Partially Dispatched."))
        if not self.items:
            frappe.throw(_("Add at least one dispatch line."))
        self._validate_quantities()

    def before_complete(self):
        self._order(lock=True)
        self.calculate()
        self.validate_doc()

    def stock_entries(self):
        return [
            {"product": r.product, "stage": "Finished", "qty": -flt(r.quantity)}
            for r in self.items
        ]

    def after_complete(self):
        """Called by CompletableDocument.complete() after stock is posted."""
        self._apply_so_update(+1)
        self.db_set("dispatch_status", "Dispatched")

    def before_reopen(self):
        self._order(lock=True)

    def after_reopen(self):
        self._apply_so_update(-1)
        self.db_set("dispatch_status", "Draft")

    # ------------------------------------------------------------------
    # Whitelisted UI actions
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def confirm_dispatch(self):
        """
        Confirm a Draft dispatch:
          1. Lock the SO row to prevent concurrent confirms.
          2. Refresh item info and re-validate quantities.
          3. Check Finished stock availability.
          4. Deduct Finished stock (exactly once via stock_service.post).
          5. Update SO dispatched quantities and status.
          6. Mark this dispatch as 'Dispatched'.
        """
        if self.dispatch_status not in ("Draft", "Pending Confirmation"):
            frappe.throw(
                _("Only Draft or Pending Confirmation dispatches can be confirmed. Current status: {0}.").format(
                    self.dispatch_status
                )
            )
        self.check_permission("write")

        # 1. Lock the Sales Order row to prevent concurrent dispatches
        self._order(lock=True)

        # 2. Refresh and validate
        self._refresh_item_info()
        self.validate_doc()

        # 3. Stock check
        self._check_stock()

        # 4. Post stock entries (deduct Finished stock)
        entries = self.stock_entries()
        stock_post(entries, self.doctype, self.name)

        # 5. Update Sales Order
        self._apply_so_update(+1)

        # 6. Calculate and save grand_total
        self._calc_grand_total()

        # 7. Mark confirmed
        self.db_set("dispatch_status", "Dispatched")
        return {"status": "Dispatched", "name": self.name}

    @frappe.whitelist()
    def cancel_dispatch(self):
        """
        Cancel a dispatch:
          - Draft → just mark Cancelled; no stock or SO changes.
          - Dispatched → reverse stock (once) and restore SO quantities. Requires admin.
        """
        from clssurya.utils.base import require_admin

        current = self.dispatch_status

        if current == "Draft" or current == "Pending Confirmation":
            # Safe cancel: no inventory has been touched
            self.db_set("dispatch_status", "Cancelled")
            return {"status": "Cancelled", "stock_reversed": False}

        elif current == "Dispatched":
            require_admin()
            self.check_permission("write")

            # Lock the Sales Order
            self._order(lock=True)

            # Reverse stock entries (stock_service.reverse is idempotent via is_reversed flag)
            stock_reverse(self.doctype, self.name)

            # Restore SO dispatched quantities
            self._apply_so_update(-1)

            self.db_set("dispatch_status", "Cancelled")
            return {"status": "Cancelled", "stock_reversed": True}

        else:
            frappe.throw(
                _("Dispatch {0} is already {1} and cannot be cancelled.").format(
                    self.name, current
                )
            )
