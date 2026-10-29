import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class BOM(Document):
    def validate(self):
        p = frappe.db.get_value("Product", self.product, ["product_type", "total_steps", "finished_good_type"], as_dict=True)
        if not p:
            frappe.throw(_("Product {0} not found.").format(self.product))
        if p.product_type == "Raw":
            frappe.throw(_("A BOM is only for Semi / Finished products."))

        self.total_steps = cint(p.total_steps)
        is_belt = (p.product_type == "Finished" and p.finished_good_type == "Belt")

        if is_belt:
            # Belt products start at Stage 2 (consuming Roll products created independently in Stage 1)
            if self.stage1_items:
                frappe.throw(_("Stage 1 rows are not applicable for Belt products. Rolls are created separately."))
            if self.total_steps >= 2 and not self.stage2_items:
                frappe.throw(_("Stage 2 Roll consumption rows are required for Belt products."))
            for r in self.stage2_items:
                ptype = frappe.db.get_value("Product", r.product, "product_type")
                if ptype not in ("Semi", "Raw"):
                    frappe.throw(_("{0}: must be a Semi (Roll) or Raw product.").format(r.product))
                if flt(r.ratio) <= 0 and flt(r.per_unit_utilization) <= 0:
                    frappe.throw(_("Ratio or utilization for {0} must be greater than 0.").format(r.product))
            for r in self.get("stage3_items") or []:
                if frappe.db.get_value("Product", r.product, "product_type") != "Raw":
                    frappe.throw(_("{0}: only Raw products can be Stage 3 component materials.").format(r.product))
                if flt(r.ratio) <= 0 and flt(r.per_unit_utilization) <= 0:
                    frappe.throw(_("Ratio or utilization for {0} must be greater than 0.").format(r.product))
        else:
            for n, table in ((1, "stage1_items"), (2, "stage2_items"), (3, "stage3_charges")):
                rows = self.get(table)
                if n <= self.total_steps and not rows:
                    frappe.throw(_("Stage {0} rows are required for {1} step(s).").format(n, self.total_steps))
                if n > self.total_steps and rows:
                    frappe.throw(_("Remove Stage {0} rows: the product has only {1} step(s).").format(n, self.total_steps))
            for r in self.stage1_items + self.stage2_items:
                if frappe.db.get_value("Product", r.product, "product_type") != "Raw":
                    frappe.throw(_("{0}: only Raw products can be BOM materials.").format(r.product))
                if flt(r.per_unit_utilization) <= 0:
                    frappe.throw(_("Utilization for {0} must be greater than 0.").format(r.product))
            for r in self.stage1_items:
                if r.wastage_product and not frappe.db.get_value("Product", r.wastage_product, "is_scrap"):
                    frappe.throw(_("{0} is not marked as scrap.").format(r.wastage_product))
