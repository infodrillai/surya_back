import frappe
from frappe import _
from frappe.utils import cint, flt

from clssurya.utils.base import CompletableDocument
from clssurya.utils.costing import stage1_wastage, stage_totals
from clssurya.utils.stock_service import inventory_price

PREV_STAGE = {2: "Stage 1", 3: "Stage 2"}
OUT_STAGE = {1: "Stage 1", 2: "Stage 2", 3: "Finished"}


class StageBatch(CompletableDocument):
    """Shared logic for Stage 1/2/3 batches. Stages link only through stock."""

    STAGE = 1

    def calculate(self):
        qty = flt(self.quantity)

        if self.STAGE > 1:
            self._ensure_carried_row(qty)

        carried = 0.0
        added = 0.0
        used = 0.0
        extra_cost_total = 0.0

        for r in self.get("items"):
            carried_in = cint(r.get("is_carried_in"))

            r.unit_price = inventory_price(
                r.product,
                PREV_STAGE[self.STAGE] if carried_in else "Raw"
            )

            r.total_utilization = flt(r.per_unit_utilization) * qty
            r.amount = r.total_utilization * r.unit_price
            r.per_unit_amount = flt(r.per_unit_utilization) * r.unit_price
            r.actual_amount = flt(r.actual_utilization) * r.unit_price

            # Avoid division by zero
            actual_qty = flt(r.actual_utilization)
            r.unit_cost = flt(r.actual_amount / actual_qty) if actual_qty else 0

            used += actual_qty

            if carried_in:
                carried += r.actual_amount
            else:
                added += r.actual_amount

            # Extra Cost / pc × batch output quantity
            row_extra_cost = flt(r.get("extra_cost")) * qty
            extra_cost_total += row_extra_cost
            added += row_extra_cost

        if self.STAGE == 3:
            for c in self.get("charges"):
                c.amount = flt(c.per_unit_price) * qty
                added += c.amount

        if self.STAGE == 1:
            self.wastage_qty = stage1_wastage(
                used, qty, self.weight_per_piece
            )

            if (
                not self.wastage_product
                and self.product
                and frappe.db.exists("BOM", self.product)
            ):
                for r in frappe.get_doc("BOM", self.product).stage1_items:
                    if r.wastage_product:
                        self.wastage_product = r.wastage_product
                        break

        t = stage_totals(
            carried,
            added,
            flt(self.rejection_percent),
            qty
        )

        self.carried_cost = carried
        self.added_cost = added
        self.rejection_amount = t["rejection_amount"]
        self.batch_total = t["batch_total"]
        self.unit_cost = t["unit_cost"]

    def _ensure_carried_row(self, qty):
        rows = [r for r in self.get("items") if cint(r.get("is_carried_in"))]
        if self.STAGE == 3:  # Stage 3 consumes the Stage 2 product + charges only
            self.set("items", rows[:1])
            rows = self.get("items")
        if not rows and self.product:
            self.append("items", {"is_carried_in": 1, "product": self.product, "per_unit_utilization": 1, "actual_utilization": qty})
        for r in self.get("items"):
            if cint(r.get("is_carried_in")):
                r.product = self.product

    def validate_doc(self):
        if flt(self.quantity) <= 0:
            frappe.throw(_("Quantity produced must be greater than 0."))
        if not 0 <= flt(self.rejection_percent) < 100:
            frappe.throw(_("Rejection % must be between 0 and 100."))
        steps = frappe.db.get_value("BOM", self.product, "total_steps") if frappe.db.exists("BOM", self.product) else None
        if steps is None:
            frappe.throw(_("No BOM found for {0}.").format(self.product))
        if cint(steps) < self.STAGE:
            frappe.throw(_("{0} has only {1} step(s) in its BOM.").format(self.product, steps))
        if any(flt(r.actual_utilization) < 0 for r in self.get("items")):
            frappe.throw(_("Actual utilization cannot be negative."))
        if self.STAGE == 1:
            if flt(self.weight_per_piece) <= 0:
                frappe.throw(_("Enter the weight of one output piece."))
            if flt(self.wastage_qty) < 0:
                frappe.throw(_("Output weight is more than the material used (wastage is negative)."))

    def stock_entries(self):
        entries = []
        for r in self.get("items"):
            stage = PREV_STAGE[self.STAGE] if cint(r.get("is_carried_in")) else "Raw"
            entries.append({"product": r.product, "stage": stage, "qty": -flt(r.actual_utilization)})
        entries.append({"product": self.product, "stage": OUT_STAGE[self.STAGE], "qty": flt(self.quantity), "unit_price": flt(self.unit_cost)})
        if self.STAGE == 1 and flt(self.wastage_qty) > 0 and self.wastage_product:
            entries.append({"product": self.wastage_product, "stage": "Raw", "qty": flt(self.wastage_qty), "unit_price": 0})
        return entries
