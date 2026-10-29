import frappe
from frappe import _
from frappe.utils import cint, flt, time_diff_in_seconds

from clssurya.utils.base import CompletableDocument
from clssurya.utils.costing import stage1_wastage, stage_totals
from clssurya.utils.stock_service import inventory_price

PREV_STAGE = {2: "Stage 1", 3: "Stage 2"}
OUT_STAGE = {1: "Stage 1", 2: "Stage 2", 3: "Stage 3"}

STAGE_DISPLAY = {
    "Raw": "Raw Material",
    "Stage 1": "Stage 1 (Insert / Roll Making)",
    "Stage 2": "Stage 2 (PU / Belt Sizing)",
    "Stage 3": "Stage 3 (CNC / Belt Finishing)",
    "Finished": "Finished Goods",
}

class StageBatch(CompletableDocument):
    """Shared logic for Stage 1/2/3 batches (PU and Belt flows)."""

    STAGE = 1

    def _is_belt(self):
        if not getattr(self, "product", None):
            return False
        p = frappe.db.get_value("Product", self.product, ["product_type", "finished_good_type"], as_dict=True)
        return bool(p and p.product_type == "Finished" and p.finished_good_type == "Belt")

    def calculate(self):
        qty = flt(self.quantity)
        if not getattr(self, "production_code", None) and getattr(self, "product", None):
            self.production_code = frappe.db.get_value("Product", self.product, "production_code")

        is_belt = self._is_belt()

        if self.STAGE > 1:
            self._ensure_carried_row(qty)

        carried = 0.0
        added = 0.0
        used = 0.0
        extra_cost_total = 0.0
        input_material_qty = 0.0

        for r in self.get("items"):
            carried_in = cint(r.get("is_carried_in"))

            # Determine price based on source_stage or standard flow
            source_stage = r.get("source_stage")
            if source_stage:
                r.unit_price = inventory_price(r.product, source_stage)
            else:
                r.unit_price = inventory_price(
                    r.product,
                    PREV_STAGE[self.STAGE] if carried_in else "Raw"
                )

            # Belt Stage 2 dynamic utilization: (size * qty) / ratio
            if self.STAGE == 2 and is_belt and r.get("ratio"):
                s_val = flt(getattr(self, "size", 0))
                if s_val <= 0:
                    length_mm = flt(frappe.db.get_value("Product", self.product, "belt_length") or 0)
                    band = frappe.db.get_value("Product", self.product, "band_type") or ""
                    if "Grommed" in band:
                        if 1080 <= length_mm <= 1120:
                            s_val = 1.2
                        elif 1460 <= length_mm <= 1510:
                            s_val = 1.5
                        elif length_mm > 0:
                            s_val = round(length_mm / 1000.0, 3)
                        else:
                            s_val = 1.0
                    else:
                        s_val = round(length_mm / 1000.0, 3) if length_mm > 0 else 1.0
                    self.size = s_val
                ratio_val = flt(r.ratio) or 1.0
                r.per_unit_utilization = s_val / ratio_val
                r.total_utilization = r.per_unit_utilization * qty
                if not r.actual_utilization or flt(r.actual_utilization) == 0:
                    r.actual_utilization = r.total_utilization
            else:
                r.total_utilization = flt(r.per_unit_utilization) * qty

            r.amount = r.total_utilization * r.unit_price
            r.per_unit_amount = flt(r.per_unit_utilization) * r.unit_price
            r.actual_amount = flt(r.actual_utilization) * r.unit_price

            actual_qty = flt(r.actual_utilization)
            r.unit_cost = flt(r.actual_amount / actual_qty) if actual_qty else 0

            used += actual_qty

            if carried_in:
                carried += r.actual_amount
                input_material_qty += actual_qty
            else:
                added += r.actual_amount
                if self.STAGE == 1 or (self.STAGE == 2 and is_belt):
                    input_material_qty += actual_qty

            row_extra_cost = flt(r.get("extra_cost")) * qty
            extra_cost_total += row_extra_cost
            added += row_extra_cost

        if self.STAGE == 3:
            for c in self.get("charges"):
                c.amount = flt(c.per_unit_price) * qty
                added += c.amount

        if self.STAGE == 1:
            self.wastage_qty = stage1_wastage(used, qty, getattr(self, "weight_per_piece", 0))
            if not getattr(self, "wastage_product", None) and self.product and frappe.db.exists("BOM", self.product):
                for r in frappe.get_doc("BOM", self.product).stage1_items:
                    if r.wastage_product:
                        self.wastage_product = r.wastage_product
                        break

        t = stage_totals(
            carried,
            added,
            flt(self.rejection_percent),
            qty,
            rejection_per_piece=flt(self.get("rejection_per_piece")),
        )

        self.carried_cost = carried
        self.added_cost = added
        self.rejection_amount = t["rejection_amount"]
        self.batch_total = t["batch_total"]
        self.unit_cost = t["unit_cost"]
        self.unit_cost_without_rejection = t["unit_cost_without_rejection"]

        # Date-wise & Stage-wise Production Tracking fields
        self.accepted_qty = qty
        self.input_qty = input_material_qty or qty
        rej_pct = flt(self.rejection_percent)
        rej_piece = flt(self.get("rejection_per_piece"))
        if rej_piece > 0:
            self.rejected_qty = rej_piece * qty
        elif rej_pct > 0:
            self.rejected_qty = (qty * rej_pct / 100.0)
        else:
            self.rejected_qty = 0.0

        self.remaining_qty = max(0.0, flt(self.input_qty) - flt(self.accepted_qty) - flt(self.rejected_qty))

        if getattr(self, "start_time", None) and getattr(self, "end_time", None):
            try:
                diff = time_diff_in_seconds(self.end_time, self.start_time)
                if diff < 0:
                    diff += 86400.0  # overnight duration adjustment
                self.duration_mins = round(diff / 60.0, 2)
            except Exception:
                pass

        if not getattr(self, "status", None) or self.status not in ("Completed", "Cancelled"):
            self.status = "Completed" if cint(self.is_completed) else "Draft"

    def _ensure_carried_row(self, qty):
        is_belt = self._is_belt()
        if self.STAGE == 2 and is_belt:
            # Belt Stage 2 does not carry in the belt itself; it consumes Roll from Stage 1
            non_carried = [r for r in self.get("items") if not cint(r.get("is_carried_in"))]
            self.set("items", non_carried)
            return

        rows = [r for r in self.get("items") if cint(r.get("is_carried_in"))]
        if self.STAGE == 3 and not is_belt:
            # PU Stage 3 only has the carried row
            self.set("items", rows[:1])
            rows = self.get("items")

        if not rows and self.product:
            carried_row = {"is_carried_in": 1, "product": self.product, "per_unit_utilization": 1, "actual_utilization": qty}
            # Insert carried row at the top
            all_items = [carried_row] + [r for r in self.get("items") if not cint(r.get("is_carried_in"))]
            self.set("items", all_items)
            rows = [carried_row]

        for r in self.get("items"):
            if cint(r.get("is_carried_in")):
                r.product = self.product

    def validate_doc(self):
        if flt(self.quantity) <= 0:
            frappe.throw(_("Quantity produced must be greater than 0."))
        if not 0 <= flt(self.rejection_percent) < 100:
            frappe.throw(_("Rejection % must be between 0 and 100."))
        if self._is_belt() and self.STAGE == 1:
            frappe.throw(_("Stage 1 is for Roll Creation. Belt products begin at Stage 2."))
        steps = frappe.db.get_value("BOM", self.product, "total_steps") if frappe.db.exists("BOM", self.product) else None
        if steps is None:
            frappe.throw(_("No BOM found for {0}.").format(self.product))
        if cint(steps) < self.STAGE:
            frappe.throw(_("{0} has only {1} step(s) in its BOM.").format(self.product, steps))
        if any(flt(r.actual_utilization) < 0 for r in self.get("items")):
            frappe.throw(_("Actual utilization cannot be negative."))
        if self.STAGE == 1 and not self._is_belt():
            if flt(getattr(self, "weight_per_piece", 0)) <= 0:
                # Only mandatory if weight_per_piece is required (e.g. PU insert)
                pass
            if flt(getattr(self, "wastage_qty", 0)) < 0:
                frappe.throw(_("Output weight is more than the material used (wastage is negative)."))
        if flt(self.get("rejection_per_piece", 0)) < 0:
            frappe.throw(_("Rejection per piece cannot be negative."))

    def stock_entries(self):
        entries = []
        for r in self.get("items"):
            source_stage = r.get("source_stage") or (PREV_STAGE[self.STAGE] if cint(r.get("is_carried_in")) else "Raw")
            entries.append({"product": r.product, "stage": source_stage, "qty": -flt(r.actual_utilization)})

        price = flt(self.unit_cost)
        entries.append({"product": self.product, "stage": OUT_STAGE[self.STAGE], "qty": flt(self.quantity), "unit_price": price})

        if self.STAGE == 1 and flt(self.get("wastage_qty", 0)) > 0 and getattr(self, "wastage_product", None):
            entries.append({"product": self.wastage_product, "stage": "Raw", "qty": flt(self.wastage_qty), "unit_price": 0})
        return entries
