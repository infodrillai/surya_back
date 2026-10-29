import os
import frappe
from frappe.utils import flt
from clssurya.utils.stock_service import post

def seed():
    if not frappe.db:
        frappe.init(site="surya.local", sites_path=os.path.abspath("."))
        frappe.connect()
    frappe.set_user("Administrator")

    print("Seeding Belt Production Masters from Engineering Specifications...")

    # Ensure Category
    if not frappe.db.exists("Category", "Belt Materials"):
        frappe.get_doc({"doctype": "Category", "category_name": "Belt Materials"}).insert(ignore_permissions=True)
    if not frappe.db.exists("Category", "Finished Belts"):
        frappe.get_doc({"doctype": "Category", "category_name": "Finished Belts"}).insert(ignore_permissions=True)

    # 1. Seed 12 Page 6 Raw Materials
    raw_items = [
        {"code": "RAW-FABRIC", "name": "Belt Fabric", "uom": "Mtr", "price": 85.0},
        {"code": "RAW-NYLON-SHEET", "name": "Nylon Sheet", "uom": "Kg", "price": 320.0},
        {"code": "RAW-IPA", "name": "IPA (Isopropanol)", "uom": "Kg", "price": 140.0},
        {"code": "RAW-RESORCINOL", "name": "Resorcinol", "uom": "Kg", "price": 450.0},
        {"code": "RAW-NYLON-POWDER", "name": "Nylon Powder", "uom": "Kg", "price": 600.0},
        {"code": "RAW-HUB-1046M", "name": "HUB 1046M Coating Agent", "uom": "Kg", "price": 550.0},
        {"code": "RAW-CL-501", "name": "CL-501 Chemical", "uom": "Kg", "price": 750.0},
        {"code": "RAW-TOLUENE", "name": "Toluene Solvent", "uom": "Kg", "price": 120.0},
        {"code": "RAW-EYELET", "name": "Belt Eyelet", "uom": "Nos", "price": 0.85},
        {"code": "RAW-EYELET-RIVET", "name": "Eyelet Rivet", "uom": "Nos", "price": 0.65},
        {"code": "RAW-ALUM-PATTI", "name": "Aluminium Patti", "uom": "Nos", "price": 18.0},
        {"code": "RAW-ALUM-RIVET", "name": "Aluminium Rivet", "uom": "Nos", "price": 1.20},
    ]

    for item in raw_items:
        if not frappe.db.exists("Product", item["code"]):
            frappe.get_doc({
                "doctype": "Product",
                "product_code": item["code"],
                "product_name": item["name"],
                "product_type": "Raw",
                "uom": item["uom"],
                "category": "Belt Materials",
            }).insert(ignore_permissions=True)

        # Seed initial raw stock if zero
        cur_stock = flt(frappe.db.get_value("Inventory", {"product": item["code"], "stage": "Raw"}, "stock"))
        init_qty = 2000 if item["code"] == "RAW-FABRIC" else 500
        if cur_stock < init_qty:
            inv_name = frappe.db.get_value("Inventory", {"product": item["code"], "stage": "Raw"}, "name")
            if not inv_name:
                inv_name = frappe.get_doc({
                    "doctype": "Inventory",
                    "product": item["code"],
                    "stage": "Raw",
                    "stock": 0,
                    "total_amount": 0,
                    "unit_price": 0
                }).insert(ignore_permissions=True).name
            post([{"product": item["code"], "stage": "Raw", "qty": init_qty - cur_stock, "unit_price": item["price"]}], "Inventory", inv_name)

    print("✓ 12 Raw materials created with stock.")

    # 2. Seed Standard 100 mtr Roll (Semi product)
    roll_code = "ROLL-BELT-100M"
    if not frappe.db.exists("Product", roll_code):
        frappe.get_doc({
            "doctype": "Product",
            "product_code": roll_code,
            "product_name": "Standard Belt Roll (100 Mtr)",
            "product_type": "Semi",
            "total_steps": 1,
            "uom": "Mtr",
            "category": "Belt Materials",
        }).insert(ignore_permissions=True)

    # Page 6 Recipe per meter of Roll
    roll_items = [
        {"product": "RAW-FABRIC", "per_unit_utilization": 2.0},              # 200 mtr / 100
        {"product": "RAW-NYLON-SHEET", "per_unit_utilization": 0.1544411},   # 15.44411 kg / 100
        {"product": "RAW-IPA", "per_unit_utilization": 0.020853},            # 2.0853 kg / 100
        {"product": "RAW-RESORCINOL", "per_unit_utilization": 0.020853},     # 2.0853 kg / 100
        {"product": "RAW-NYLON-POWDER", "per_unit_utilization": 0.001146},   # 0.1146 kg / 100
        {"product": "RAW-HUB-1046M", "per_unit_utilization": 0.03077},       # 3.077 kg / 100
        {"product": "RAW-CL-501", "per_unit_utilization": 0.00231},          # 0.231 kg / 100
        {"product": "RAW-TOLUENE", "per_unit_utilization": 0.04615},         # 4.615 kg / 100
    ]

    if not frappe.db.exists("BOM", roll_code):
        frappe.get_doc({
            "doctype": "BOM",
            "product": roll_code,
            "total_steps": 1,
            "stage1_items": roll_items
        }).insert(ignore_permissions=True)

    # Run a Stage 1 Batch to produce 300 mtr of Roll
    roll_stock = flt(frappe.db.get_value("Inventory", {"product": roll_code, "stage": "Stage 1"}, "stock"))
    if roll_stock < 100:
        s1 = frappe.get_doc({
            "doctype": "Stage 1 Batch",
            "product": roll_code,
            "quantity": 300,
            "items": [{"product": r["product"], "per_unit_utilization": r["per_unit_utilization"], "actual_utilization": r["per_unit_utilization"] * 300} for r in roll_items]
        })
        s1.insert(ignore_permissions=True)
        s1.complete()
        print(f"✓ Initial Roll Batch created: 300 Mtr in Stage 1 stock.")

    # 3. Seed Sample Belt Products from Pages 1 to 5
    sample_belts = [
        {
            "code": "BELT-GROMMED-ALUM-1492",
            "name": "Grommed Band 1492x81.5x7 w/ Alum Patti",
            "band_type": "Grommed with Aluminium Patti",
            "length": 1492,
            "width": 81.5,
            "hole": 7,
            "ratio": 3.0,
            "has_patti": True,
        },
        {
            "code": "BELT-GROMMED-1095",
            "name": "Grommed Band 1095x98x10",
            "band_type": "Grommed",
            "length": 1095,
            "width": 98,
            "hole": 10,
            "ratio": 3.0,
            "has_patti": False,
        },
        {
            "code": "BELT-GROMMED-WIDE-1095",
            "name": "Grommed Band 1095x138x15 (Wide)",
            "band_type": "Grommed",
            "length": 1095,
            "width": 138,
            "hole": 15,
            "ratio": 2.0,
            "has_patti": False,
        },
        {
            "code": "BELT-LOWER-460",
            "name": "Lower Belt 460x98x10",
            "band_type": "Lower",
            "length": 460,
            "width": 98,
            "hole": 10,
            "ratio": 3.0,
            "has_patti": False,
        },
        {
            "code": "BELT-LOWER-WIDE-463",
            "name": "Lower Belt 463x118x12 (Wide)",
            "band_type": "Lower",
            "length": 463,
            "width": 118,
            "hole": 12,
            "ratio": 2.0,
            "has_patti": False,
        },
        {
            "code": "BELT-UPPER-230",
            "name": "Upper Belt 230x98x10",
            "band_type": "Upper",
            "length": 230,
            "width": 98,
            "hole": 10,
            "ratio": 3.0,
            "has_patti": False,
        },
        {
            "code": "BELT-UPPER-WIDE-230",
            "name": "Upper Belt 230x122x18 (Wide)",
            "band_type": "Upper",
            "length": 230,
            "width": 122,
            "hole": 18,
            "ratio": 2.0,
            "has_patti": False,
        },
    ]

    for b in sample_belts:
        if not frappe.db.exists("Product", b["code"]):
            frappe.get_doc({
                "doctype": "Product",
                "product_code": b["code"],
                "product_name": b["name"],
                "product_type": "Finished",
                "finished_good_type": "Belt",
                "band_type": b["band_type"],
                "belt_length": b["length"],
                "belt_width": b["width"],
                "hole": b["hole"],
                "total_steps": 3,
                "uom": "Nos",
                "category": "Finished Belts",
            }).insert(ignore_permissions=True)

        stage3_items = [
            {"product": "RAW-EYELET", "calculation_type": "Hole", "ratio": 4.0},
            {"product": "RAW-EYELET-RIVET", "calculation_type": "Hole", "ratio": 4.0},
        ]
        if b["has_patti"]:
            stage3_items.extend([
                {"product": "RAW-ALUM-PATTI", "calculation_type": "Quantity", "ratio": 2.0},
                {"product": "RAW-ALUM-RIVET", "calculation_type": "Quantity", "ratio": 4.0},
            ])

        if not frappe.db.exists("BOM", b["code"]):
            frappe.get_doc({
                "doctype": "BOM",
                "product": b["code"],
                "total_steps": 3,
                "stage2_items": [
                    {"product": roll_code, "ratio": b["ratio"]},
                ],
                "stage3_items": stage3_items,
            }).insert(ignore_permissions=True)

    frappe.db.commit()
    print("✓ All 7 real-world sample belts and BOMs seeded successfully!")

if __name__ == "__main__":
    seed()
