import frappe
from frappe import _
from frappe.utils import cint, flt, time_diff_in_seconds

from clssurya.utils.base import CompletableDocument
from clssurya.utils.costing import stage1_wastage, stage_totals
from clssurya.utils.stock_service import inventory_price
from clssurya.utils.batch_tracking import source_batch_unit_cost, validate_source_batch_consumption

PREV_STAGE = {2: "Stage 1", 3: "Stage 2"}
OUT_STAGE = {1: "Stage 1", 2: "Stage 2", 3: "Stage 3"}

STAGE_DISPLAY = {
    "Raw": "Raw Material",
    "Stage 1": "Stage 1 (Insert / Roll Making)",
    "Stage 2": "Stage 2 (PU / Belt Sizing)",
    "Stage 3": "Stage 3 (CNC / Belt Finishing)",
    "Finished": "Finished Goods",
}


def stage1_carry_cost(product, bom=None):
    if not product:
        return 0.0

    # 1. Check Inventory at Stage 1
    valuation = frappe.db.get_value(
        "Inventory", {"product": product, "stage": "Stage 1"}, ["stock", "unit_price"], as_dict=True
    )
    if valuation and flt(valuation.unit_price) > 0:
        return flt(valuation.unit_price)

    # 2. Check completed Stage 1 Batch
    batch_cost = frappe.db.get_value(
        "Stage 1 Batch",
        {"product": product, "is_completed": 1},
        "unit_cost",
        order_by="completed_on desc, modified desc, name desc",
    )
    if batch_cost is not None and flt(batch_cost) > 0:
        return flt(batch_cost)

    # 3. Check any latest Stage 1 Batch (even if draft)
    latest_s1 = frappe.db.get_value(
        "Stage 1 Batch",
        {"product": product},
        "unit_cost",
        order_by="modified desc, name desc",
    )
    if latest_s1 is not None and flt(latest_s1) > 0:
        return flt(latest_s1)

    # 4. Check Stock Ledger Entry for this product at Stage 1
    try:
        sle = frappe.db.sql("""
            SELECT unit_price FROM `tabStock Ledger Entry`
            WHERE product = %s AND stage = 'Stage 1' AND unit_price > 0
            ORDER BY posting_datetime DESC, creation DESC LIMIT 1
        """, (product,))
        if sle and flt(sle[0][0]) > 0:
            return flt(sle[0][0])
    except Exception:
        pass

    # 5. Check prior Stage 2 Batch where this carrier product was used
    try:
        prev_s2 = frappe.db.sql("""
            SELECT unit_price FROM `tabStage 2 Batch Item`
            WHERE product = %s AND unit_price > 0
            ORDER BY creation DESC LIMIT 1
        """, (product,))
        if prev_s2 and flt(prev_s2[0][0]) > 0:
            return flt(prev_s2[0][0])
    except Exception:
        pass

    # 6. Check BOM Stage 1 recipe calculation
    try:
        bom = bom if bom is not None else (frappe.get_doc("BOM", product) if frappe.db.exists("BOM", product) else None)
        if bom and bom.get("stage1_items"):
            cost = 0.0
            for row in bom.get("stage1_items"):
                p = inventory_price(row.product, "Raw")
                if not p:
                    pe_row = frappe.db.sql("""
                        SELECT rate FROM `tabPurchase Entry Item`
                        WHERE product = %s AND rate > 0
                        ORDER BY creation DESC LIMIT 1
                    """, (row.product,))
                    p = flt(pe_row[0][0]) if pe_row else 0.0
                if not p:
                    p = flt(frappe.db.get_value("Product", row.product, "last_purchase_rate")) or flt(frappe.db.get_value("Product", row.product, "valuation_rate")) or 0.0
                cost += flt(row.per_unit_utilization) * p
            if cost > 0:
                return cost
    except Exception:
        pass

    # 7. Check direct Purchase Entry Item rate (if carrier was purchased)
    try:
        pe = frappe.db.sql("""
            SELECT rate FROM `tabPurchase Entry Item`
            WHERE product = %s AND rate > 0
            ORDER BY creation DESC LIMIT 1
        """, (product,))
        if pe and flt(pe[0][0]) > 0:
            return flt(pe[0][0])
    except Exception:
        pass

    # 8. Check product master price / cost
    prod = frappe.db.get_value("Product", product, ["production_cost", "valuation_rate", "standard_rate", "last_purchase_rate"], as_dict=True)
    if prod:
        return flt(prod.production_cost) or flt(prod.valuation_rate) or flt(prod.standard_rate) or flt(prod.last_purchase_rate) or 0.0

    return 0.0


class StageBatch(CompletableDocument):
    """Shared logic for Stage 1/2/3 batches (PU and Belt flows)."""

    STAGE = 1

    def after_complete(self):
        # Create rejection history in the same completion transaction as stock posting.
        from clssurya.utils.rejections import sync_rejection_entry

        sync_rejection_entry(self)

    def after_reopen(self):
        # Keep the generated document for audit, but remove its active quantity.
        from clssurya.utils.rejections import deactivate_rejection_entry

        deactivate_rejection_entry(self)

    def before_complete(self):
        validate_source_batch_consumption(self, lock=True)

    def before_reopen(self):
        validate_source_batch_consumption(self, lock=True)

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
            batch_price = source_batch_unit_cost(r) if r.get("source_batch") else None
            if batch_price is not None:
                r.unit_price = batch_price
            elif self.STAGE == 2 and carried_in and not is_belt and source_stage in (None, "", "Stage 1"):
                r.unit_price = stage1_carry_cost(r.product)
            elif source_stage:
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
                if not r.get("source_batch") and (not r.actual_utilization or flt(r.actual_utilization) == 0):
                    r.actual_utilization = r.total_utilization
            else:
                r.total_utilization = flt(r.per_unit_utilization) * qty

            r.amount = r.total_utilization * r.unit_price
            r.per_unit_amount = flt(r.per_unit_utilization) * r.unit_price
            r.actual_amount = flt(r.actual_utilization) * r.unit_price

            actual_qty = flt(r.actual_utilization)
            r.unit_cost = flt(r.actual_amount / actual_qty) if actual_qty else 0

            used += actual_qty

            if carried_in or r.get("source_batch"):
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
            if not any(r.get("source_batch") for r in rows):
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
        validate_source_batch_consumption(self)

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
