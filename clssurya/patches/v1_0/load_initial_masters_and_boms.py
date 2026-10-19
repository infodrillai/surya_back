import json
import os
import frappe
from frappe.utils import cint, flt


def get_data_filepath():
    """Returns absolute path to initial_masters.json."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "initial_masters.json",
    )


def execute():
    """Standard Frappe patch execution entry point."""
    load_initial_masters_and_boms()


def load_initial_masters_and_boms(filepath=None, force=False):
    """Load UOMs, Categories, Processes, Charges, Products, and BOMs from seed JSON.

    - Safe & idempotent: skips documents that already exist unless force=True.
    - Preserves data integrity: verifies prerequisite foreign keys before insertion.
    - Synchronizes offline cache: increments Master Version counter once upon completion.
    """
    path = filepath or get_data_filepath()
    if not os.path.exists(path):
        frappe.throw(f"Master seed data file not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    inserted_counts = {
        "UOM": 0,
        "Category": 0,
        "Process": 0,
        "Charge": 0,
        "Product": 0,
        "BOM": 0,
    }

    # 1. Prerequisite: Categories
    for cat in data.get("categories", []):
        name = cat.get("category_name") or cat.get("name")
        if name and not frappe.db.exists("Category", name):
            doc = frappe.get_doc({
                "doctype": "Category",
                "category_name": name,
            })
            doc.insert(ignore_permissions=True)
            inserted_counts["Category"] += 1

    # 2. Prerequisite: Processes
    for proc in data.get("processes", []):
        name = proc.get("process_name") or proc.get("name")
        if name and not frappe.db.exists("Process", name):
            doc = frappe.get_doc({
                "doctype": "Process",
                "process_name": name,
            })
            doc.insert(ignore_permissions=True)
            inserted_counts["Process"] += 1

    # 3. Prerequisite: Charges
    for ch in data.get("charges", []):
        name = ch.get("charge_name") or ch.get("name")
        if name and not frappe.db.exists("Charge", name):
            doc = frappe.get_doc({
                "doctype": "Charge",
                "charge_name": name,
            })
            doc.insert(ignore_permissions=True)
            inserted_counts["Charge"] += 1

    # 4. Prerequisite: UOMs
    for uom in data.get("uoms", []):
        name = uom.get("uom_name") or uom.get("name")
        if name and not frappe.db.exists("UOM", name):
            doc = frappe.get_doc({
                "doctype": "UOM",
                "uom_name": name,
            })
            doc.insert(ignore_permissions=True)
            inserted_counts["UOM"] += 1

    # 5. Products
    existing_products = set(frappe.db.get_all("Product", pluck="name"))
    for p in data.get("products", []):
        code = p.get("product_code")
        if not code:
            continue

        if code not in existing_products:
            p_type = p.get("product_type") or "Finished"
            total_steps = p.get("total_steps")
            if p_type == "Raw":
                total_steps = 0
            elif not total_steps:
                total_steps = 3

            doc = frappe.get_doc({
                "doctype": "Product",
                "product_name": p.get("product_name") or code,
                "product_code": code,
                "product_type": p_type,
                "uom": p.get("uom") or "QTY",
                "is_scrap": cint(p.get("is_scrap", 0)),
                "low_stock_limit": flt(p.get("low_stock_limit", 0)),
                "high_stock_limit": flt(p.get("high_stock_limit", 0)),
                "category": p.get("category"),
                "total_steps": cint(total_steps),
                "allow_negative_stock": cint(p.get("allow_negative_stock", 0)),
            })
            doc.flags.ignore_permissions = True
            doc.insert()
            existing_products.add(code)
            inserted_counts["Product"] += 1
        elif force:
            doc = frappe.get_doc("Product", code)
            doc.product_name = p.get("product_name") or doc.product_name
            doc.product_type = p.get("product_type") or doc.product_type
            doc.uom = p.get("uom") or doc.uom
            doc.is_scrap = cint(p.get("is_scrap", doc.is_scrap))
            doc.low_stock_limit = flt(p.get("low_stock_limit", doc.low_stock_limit))
            doc.high_stock_limit = flt(p.get("high_stock_limit", doc.high_stock_limit))
            doc.category = p.get("category") or doc.category
            doc.total_steps = cint(p.get("total_steps") or (0 if doc.product_type == "Raw" else 3))
            doc.allow_negative_stock = cint(p.get("allow_negative_stock", doc.allow_negative_stock))
            doc.flags.ignore_permissions = True
            doc.save()

    # 6. BOMs
    existing_boms = set(frappe.db.get_all("BOM", pluck="name"))
    for b in data.get("boms", []):
        prod = b.get("product")
        if not prod:
            continue

        if prod not in existing_products and not frappe.db.exists("Product", prod):
            continue

        if prod not in existing_boms:
            doc = frappe.get_doc({
                "doctype": "BOM",
                "product": prod,
                "total_steps": cint(b.get("total_steps", 3)),
                "stage1_items": b.get("stage1_items", []),
                "stage2_items": b.get("stage2_items", []),
                "stage3_charges": b.get("stage3_charges", []),
            })
            doc.flags.ignore_permissions = True
            doc.insert()
            existing_boms.add(prod)
            inserted_counts["BOM"] += 1
        elif force:
            doc = frappe.get_doc("BOM", prod)
            doc.total_steps = cint(b.get("total_steps", doc.total_steps))
            doc.set("stage1_items", b.get("stage1_items", []))
            doc.set("stage2_items", b.get("stage2_items", []))
            doc.set("stage3_charges", b.get("stage3_charges", []))
            doc.flags.ignore_permissions = True
            doc.save()

    frappe.db.commit()

    # 7. Update Master Version cache invalidation if any records were inserted
    any_inserted = any(count > 0 for count in inserted_counts.values())
    if any_inserted or force:
        try:
            from clssurya.utils.versions import get_versions
            versions = get_versions()
            for dt in ["UOM", "Product", "BOM", "Category", "Process", "Charge"]:
                versions[dt] = int(versions.get(dt, 0)) + 1
            frappe.db.set_single_value("Master Version", "versions", json.dumps(versions))
            frappe.db.commit()
        except Exception:
            pass

    print(
        f"[clssurya] Masters & BOMs load finished. Inserted: "
        f"UOM: {inserted_counts['UOM']}, "
        f"Category: {inserted_counts['Category']}, "
        f"Process: {inserted_counts['Process']}, "
        f"Charge: {inserted_counts['Charge']}, "
        f"Product: {inserted_counts['Product']}, "
        f"BOM: {inserted_counts['BOM']}"
    )

    return inserted_counts
