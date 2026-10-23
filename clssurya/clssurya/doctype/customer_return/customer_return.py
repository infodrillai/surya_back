"""
Customer Return DocType controller.

Lifecycle:
  insert()          → return_status = 'Draft'  (no stock effect)
  confirm_return()  → return_status = 'Confirmed'
                       – Usable items → add back to Finished inventory
                       – Damaged / Requires Inspection → add to 'Damaged' stage (separate)
                       – Create Stock Ledger Entries via stock_service.post
                       – Update Sales Order Item returned_qty / net_delivered_qty
  cancel_return()   → return_status = 'Cancelled'
                       – Confirmed: reverse stock (stock_service.reverse) + restore SO qtys
                       – Draft: just mark Cancelled
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate

from clssurya.utils.base import require_admin
from clssurya.utils.stock_service import inventory_price, post as stock_post, reverse as stock_reverse

EPS = 1e-6

# The stage name used for damaged / inspection-required goods
DAMAGED_STAGE = "Damaged"


class CustomerReturn(Document):

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch(self):
        if not self.dispatch:
            frappe.throw(_("A Dispatch reference is required."))
        return frappe.get_doc("Dispatch", self.dispatch)

    def _get_confirmed_returned_qty(self, dispatch_item_name, exclude_self=True):
        """Sum of return_qty already Confirmed for this dispatch item row (excludes self)."""
        filters = {
            "dispatch": self.dispatch,
            "return_status": "Confirmed",
        }
        confirmed = frappe.get_all(
            "Customer Return",
            filters=filters,
            pluck="name",
        )
        if exclude_self and self.name:
            confirmed = [c for c in confirmed if c != self.name]

        total = 0.0
        for rname in confirmed:
            rdoc = frappe.get_doc("Customer Return", rname)
            for row in rdoc.items:
                if row.dispatch_item == dispatch_item_name:
                    total += flt(row.return_qty)
        return total

    def _validate_quantities(self):
        """Validate each return row qty > 0 and ≤ returnable qty."""
        seen_items = {}
        for row in self.items:
            if flt(row.return_qty) <= 0:
                frappe.throw(
                    _("Row {0}: return quantity must be greater than 0.").format(row.idx)
                )
            # Check duplicate dispatch_item in the same return
            if row.dispatch_item in seen_items:
                frappe.throw(
                    _("Row {0}: product {1} appears more than once. Combine into a single row.").format(
                        row.idx, row.product
                    )
                )
            seen_items[row.dispatch_item] = True

            already = self._get_confirmed_returned_qty(row.dispatch_item)
            returnable = flt(row.dispatched_qty) - already
            if flt(row.return_qty) > returnable + EPS:
                pname = frappe.db.get_value("Product", row.product, "product_name") or row.product
                frappe.throw(
                    _("Row {0} ({1}): cannot return {2}; only {3} returnable "
                      "(dispatched {4} − already confirmed {5}).").format(
                        row.idx, pname,
                        flt(row.return_qty, 4), flt(returnable, 4),
                        flt(row.dispatched_qty, 4), flt(already, 4),
                    )
                )

    def _refresh_from_dispatch(self):
        """Populate read-only header fields and item metadata from the Dispatch."""
        disp = self._dispatch()
        self.sales_order = disp.sales_order
        self.customer = disp.customer
        disp_items = {r.name: r for r in disp.items}

        for row in self.items:
            di = disp_items.get(row.dispatch_item)
            if not di:
                frappe.throw(
                    _("Row {0}: dispatch item row '{1}' not found in dispatch {2}.").format(
                        row.idx, row.dispatch_item, self.dispatch
                    )
                )
            row.product = di.product
            row.order_item = di.order_item
            row.dispatched_qty = flt(di.quantity)
            row.unit_cost = inventory_price(row.product, "Finished") or flt(di.unit_cost)
            row.already_returned = self._get_confirmed_returned_qty(row.dispatch_item)
            row.returnable_qty = max(0.0, row.dispatched_qty - row.already_returned)

    # ------------------------------------------------------------------
    # Frappe hooks
    # ------------------------------------------------------------------

    def validate(self):
        before = self.get_doc_before_save()
        if before and before.return_status in ("Confirmed", "Cancelled"):
            frappe.throw(
                _("A {0} return cannot be edited.").format(before.return_status)
            )
        self.return_status = "Draft"
        if not self.items:
            frappe.throw(_("Add at least one return item."))
        if not (self.return_date):
            self.return_date = nowdate()
        self._refresh_from_dispatch()
        self._validate_quantities()

    def on_trash(self):
        if self.return_status == "Confirmed":
            frappe.throw(_("A confirmed return cannot be deleted. Cancel it first."))

    # ------------------------------------------------------------------
    # Helper: update SO returned / net-delivered quantities
    # ------------------------------------------------------------------

    def _apply_so_update(self, sign):
        """
        sign = +1 when confirming (adding return qty to returned_qty)
               -1 when reversing (subtracting return qty from returned_qty)
        Updates returned_qty and net_delivered_qty on each Sales Order Item row.
        """
        so = frappe.get_doc("Sales Order", self.sales_order)
        so_items = {l.name: l for l in so.items}

        for row in self.items:
            line = so_items.get(row.order_item)
            if not line:
                continue
            new_returned = max(0.0, flt(line.returned_qty) + sign * flt(row.return_qty))
            net_delivered = max(0.0, flt(line.dispatched_qty) - new_returned)
            frappe.db.set_value(
                "Sales Order Item",
                line.name,
                {
                    "returned_qty": new_returned,
                    "net_delivered_qty": net_delivered,
                },
            )

    # ------------------------------------------------------------------
    # Stock entries for usable and damaged goods
    # ------------------------------------------------------------------

    def _stock_entries_for_return(self):
        """Build stock entries: usable → Finished (+), damaged/inspection → Damaged (+)."""
        entries = []
        for row in self.items:
            qty = flt(row.return_qty)
            if qty <= 0:
                continue
            stage = "Finished" if row.condition == "Usable" else DAMAGED_STAGE
            price = flt(row.unit_cost)
            entries.append({
                "product": row.product,
                "stage": stage,
                "qty": qty,
                "unit_price": price,
            })
        return entries

    # ------------------------------------------------------------------
    # Whitelisted actions
    # ------------------------------------------------------------------

    @frappe.whitelist()
    def confirm_return(self):
        """
        Confirm a Draft return:
          1. Lock the Dispatch row against concurrent operations.
          2. Refresh item metadata and re-validate quantities.
          3. Post stock: usable → Finished, damaged → Damaged stage.
          4. Update Sales Order Item returned/net-delivered quantities.
          5. Mark Confirmed (exactly once, transactional).
        """
        if self.return_status != "Draft":
            frappe.throw(
                _("Only Draft returns can be confirmed. Current status: {0}.").format(
                    self.return_status
                )
            )
        self.check_permission("write")

        # 1. Lock dispatch to prevent concurrent confirmations
        frappe.db.sql(
            "SELECT name FROM `tabDispatch` WHERE name=%s FOR UPDATE",
            (self.dispatch,),
        )

        # Make sure the parent dispatch is in Dispatched state
        disp_status = frappe.db.get_value("Dispatch", self.dispatch, "dispatch_status")
        if disp_status != "Dispatched":
            frappe.throw(
                _("Returns can only be made against a confirmed (Dispatched) dispatch. "
                  "Dispatch {0} is currently '{1}'.").format(self.dispatch, disp_status)
            )

        # 2. Refresh and validate
        self._refresh_from_dispatch()
        self._validate_quantities()

        # 3. Post stock entries
        entries = self._stock_entries_for_return()
        stock_post(entries, self.doctype, self.name)

        # 4. Update Sales Order quantities
        self._apply_so_update(+1)

        # 5. Mark confirmed
        self.db_set({
            "return_status": "Confirmed",
            "confirmed_by": frappe.session.user,
            "confirmed_on": now_datetime(),
        })
        return {"status": "Confirmed", "name": self.name}

    @frappe.whitelist()
    def cancel_return(self):
        """
        Cancel a return:
          - Draft → just mark Cancelled; no stock/SO changes.
          - Confirmed → reverse stock (once) and restore SO quantities. Requires admin.
        """
        current = self.return_status

        if current == "Draft":
            self.db_set({
                "return_status": "Cancelled",
                "cancelled_by": frappe.session.user,
                "cancelled_on": now_datetime(),
            })
            return {"status": "Cancelled", "stock_reversed": False}

        elif current == "Confirmed":
            require_admin()
            self.check_permission("write")

            # Reverse stock entries (idempotent via is_reversed flag)
            stock_reverse(self.doctype, self.name)

            # Restore SO quantities
            self._apply_so_update(-1)

            self.db_set({
                "return_status": "Cancelled",
                "cancelled_by": frappe.session.user,
                "cancelled_on": now_datetime(),
            })
            return {"status": "Cancelled", "stock_reversed": True}

        else:
            frappe.throw(
                _("Return {0} is already Cancelled and cannot be cancelled again.").format(self.name)
            )
