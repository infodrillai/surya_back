import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from clssurya.utils.base import CompletableDocument
from clssurya.utils.stock_service import inventory_price

EPS = 1e-6  # increased tolerance to avoid rounding‑error validation failures
class Dispatch(CompletableDocument):
    def _order(self, lock=False):
        if not self.sales_order:
            frappe.throw(_("Select a sales order."))
        if lock:
            frappe.db.sql("select name from `tabSales Order` where name=%s for update", (self.sales_order,))
        return frappe.get_doc("Sales Order", self.sales_order)

    def calculate(self):
        so = self._order()
        self.customer = so.customer
        lines = {r.name: r for r in so.items}
        for r in self.items:
            line = lines.get(r.order_item)
            if not line:
                frappe.throw(_("Row {0}: order line not found.").format(r.idx))
            r.product, r.ordered_qty, r.already_dispatched = line.product, line.quantity, line.dispatched_qty
            r.unit_cost = inventory_price(r.product, "Finished")
            # Set default dispatch quantity to the remaining quantity on the order
            r.quantity = flt(r.ordered_qty) - flt(r.already_dispatched)

    def validate_doc(self):
        if self._order().status not in ("Approved", "Partially Dispatched"):
            frappe.throw(_("The order must be Approved or Partially Dispatched."))
        if not self.items:
            frappe.throw(_("Add at least one line."))
        for r in self.items:
            if flt(r.quantity) <= 0:
                frappe.throw(_("Row {0}: quantity must be above 0.").format(r.idx))
            if flt(r.quantity) > flt(r.ordered_qty) - flt(r.already_dispatched) + EPS:
                frappe.throw(_("Row {0}: cannot dispatch more than the remaining {1}.").format(r.idx, flt(r.ordered_qty) - flt(r.already_dispatched)))
    
    def before_complete(self):
        self._order(lock=True)
        self.calculate()
        self.validate_doc()  # re-check remaining quantity under the order lock

    def stock_entries(self):
        return [{"product": r.product, "stage": "Finished", "qty": -flt(r.quantity)} for r in self.items]

    def _apply(self, sign):
        so = self._order()
        for r in self.items:
            line = next(l for l in so.items if l.name == r.order_item)
            done = max(0.0, flt(line.dispatched_qty) + sign * flt(r.quantity))
            frappe.db.set_value("Sales Order Item", line.name, {"dispatched_qty": done, "pending_qty": flt(line.quantity) - done})
        so.reload()
        all_done = all(flt(l.dispatched_qty) >= flt(l.quantity) - EPS for l in so.items)
        any_done = any(flt(l.dispatched_qty) > EPS for l in so.items)
        status = "Completed" if all_done else "Partially Dispatched" if any_done else "Approved"
        flag = {"is_completed": 1, "completed_on": now_datetime(), "completed_by": frappe.session.user} if all_done else {"is_completed": 0, "completed_on": None, "completed_by": None}
        so.db_set({"status": status, **flag})

    def cancel(self):
        """Cancel a pending dispatch without affecting stock or sales order."""
        if self.dispatch_status not in ("Draft", "Pending"):
            frappe.throw(_("Only Draft or Pending dispatches can be cancelled."))
        self.db_set("dispatch_status", "Cancelled")

    @frappe.whitelist()
    def cancel_dispatch(self):
        """Whitelisted version – called from the UI Cancel button."""
        self.cancel()
        return {"status": "Cancelled"}

    def after_complete(self):
        """Called by CompletableDocument.complete() – apply stock and update status."""
        self._apply(1)
        # Set dispatch_status to 'Dispatched'
        self.db_set("dispatch_status", "Dispatched")

    @frappe.whitelist()
    def confirm_dispatch(self):
        """Whitelisted – confirm the dispatch, deduct stock, update Sales Order status."""
        if self.dispatch_status not in ("Draft", "Pending"):
            frappe.throw(_("Only Draft or Pending dispatches can be confirmed."))
        self._order(lock=True)
        self.calculate()
        self.validate_doc()
        self._apply(1)
        self.db_set("dispatch_status", "Dispatched")
        return {"status": "Dispatched"}

    def before_reopen(self):
        self._order(lock=True)

    def after_reopen(self):
        self._apply(-1)
