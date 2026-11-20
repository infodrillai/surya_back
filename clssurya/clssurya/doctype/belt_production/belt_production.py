import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class BeltProduction(Document):
    def validate(self):
        product = frappe.db.get_value(
            "Product",
            self.product,
            ["product_type", "finished_good_type", "total_steps", "hole"],
            as_dict=True,
        )
        if not product:
            frappe.throw(_("Product {0} was not found.").format(self.product))
        if product.product_type not in ("Finished", "Semi") or product.finished_good_type != "Belt":
            frappe.throw(_("Belt Production can only be configured for a belt product."))

        self.total_steps = cint(product.total_steps) or 4
        steps = self.total_steps
        if steps not in (1, 2, 3, 4):
            frappe.throw(_("Belt production must have between 1 and 4 steps."))

        stage_tables = {
            1: ("stage1_items", steps in (1, 2, 4), steps in (1, 2, 4)),
            2: ("stage2_items", steps in (2, 3, 4), steps in (2, 3, 4)),
            3: ("stage3_items", steps in (3, 4), steps in (3, 4)),
            4: ("stage4_charges", steps in (3, 4), False),
        }
        for stage, (fieldname, allowed, required) in stage_tables.items():
            rows = self.get(fieldname) or []
            if required and not rows:
                frappe.throw(_("Stage {0} rows are required.").format(stage))
            if not allowed and rows:
                frappe.throw(_("Remove Stage {0} rows; this product has {1} steps.").format(stage, steps))

        for row in self.get("stage1_items") or []:
            if flt(row.per_unit_utilization) <= 0:
                frappe.throw(_("Stage 1 utilization for {0} must be greater than zero.").format(row.product))

        for row in self.get("stage2_items") or []:
            product_type = frappe.db.get_value("Product", row.product, "product_type")
            if product_type not in ("Raw", "Semi"):
                frappe.throw(_("Stage 2 material {0} must be Raw or Semi.").format(row.product))
            if flt(row.ratio) <= 0 and flt(row.per_unit_utilization) <= 0:
                frappe.throw(_("Stage 2 ratio or utilization for {0} must be greater than zero.").format(row.product))

        for row in self.get("stage3_items") or []:
            if frappe.db.get_value("Product", row.product, "product_type") not in ("Raw", "Semi"):
                frappe.throw(_("Stage 3 material {0} must be Raw or Semi.").format(row.product))
            if flt(row.ratio) <= 0 and flt(row.per_unit_utilization) <= 0:
                frappe.throw(_("Stage 3 ratio or utilization for {0} must be greater than zero.").format(row.product))

        for row in self.get("stage4_charges") or []:
            if flt(row.per_unit_price) < 0:
                frappe.throw(_("Production charge cannot be negative."))
