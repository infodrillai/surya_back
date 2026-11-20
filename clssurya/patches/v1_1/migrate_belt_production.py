import frappe


def execute():
    """Copy belt recipes out of the shared BOM DocType, preserving old batches."""
    if not frappe.db.exists("DocType", "Belt Production"):
        return

    for name in frappe.get_all("BOM", pluck="name"):
        savepoint = "migrate_belt_recipe"
        frappe.db.savepoint(savepoint)
        try:
            product = frappe.db.get_value(
                "Product", name, ["product_type", "finished_good_type"], as_dict=True
            )
            if not product or product.product_type not in ("Finished", "Semi") or product.finished_good_type != "Belt":
                continue
            if frappe.db.exists("Belt Production", name):
                continue

            source = frappe.get_doc("BOM", name)
            target = frappe.get_doc({
                "doctype": "Belt Production",
                "product": name,
                "total_steps": source.total_steps or 4,
                "stage1_items": [{key: row.get(key) for key in ("process", "product", "per_unit_utilization", "wastage_product")} for row in source.get("stage1_items") or []],
                "stage2_items": [{key: row.get(key) for key in ("process", "product", "per_unit_utilization", "ratio")} for row in source.get("stage2_items") or []],
                "stage3_items": [{key: row.get(key) for key in ("process", "product", "calculation_type", "ratio", "per_unit_utilization")} for row in source.get("stage3_items") or []],
                "stage4_charges": [{key: row.get(key) for key in ("charge", "per_unit_price")} for row in source.get("stage3_charges") or []],
            })
            target.flags.ignore_permissions = True
            target.insert()
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            frappe.log_error(frappe.get_traceback(), f"Belt Production migration failed: {name}")

    frappe.db.commit()
