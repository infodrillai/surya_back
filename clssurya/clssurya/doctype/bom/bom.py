import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class BOM(Document):
    def validate(self):
        p = frappe.db.get_value("Product", self.product, ["product_type", "total_steps"], as_dict=True)
        if p.product_type == "Raw":
            frappe.throw(_("A BOM is only for Semi / Finished products."))
        self.total_steps = cint(p.total_steps)
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
