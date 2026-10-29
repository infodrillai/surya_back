import sys
import os

# Connect to Frappe environment
import frappe
from frappe.utils import flt
from clssurya.utils.stock_service import inventory_price, post
from clssurya.api import get_stage_rows, get_finished_cost, get_inventory_bifurcation

def run_tests():
    print("=" * 60)
    print("STARTING BELT PRODUCTION FLOW VERIFICATION TEST")
    print("=" * 60)

    frappe.init(site="surya.local", sites_path=os.path.abspath("."))
    frappe.connect()
    frappe.set_user("Administrator")

    # 1. Ensure UOM and Category
    if not frappe.db.exists("UOM", "Nos"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
    if not frappe.db.exists("UOM", "Kg"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Kg"}).insert(ignore_permissions=True)
    if not frappe.db.exists("UOM", "Mtr"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Mtr"}).insert(ignore_permissions=True)
    if not frappe.db.exists("Category", "Belt Components"):
        frappe.get_doc({"doctype": "Category", "category_name": "Belt Components"}).insert(ignore_permissions=True)

    # 2. Setup Raw Materials
    raw_materials = [
        {"code": "RAW-RUBBER-BLK", "name": "Rubber Compound Black", "uom": "Kg", "price": 200.0, "initial_stock": 500},
        {"code": "RAW-CORD-CANVAS", "name": "Canvas Cord 50mm", "uom": "Mtr", "price": 50.0, "initial_stock": 500},
        {"code": "RAW-RIVET-M4", "name": "Brass Rivet M4", "uom": "Nos", "price": 2.5, "initial_stock": 2000},
    ]

    for rm in raw_materials:
        if not frappe.db.exists("Product", rm["code"]):
            frappe.get_doc({
                "doctype": "Product",
                "product_code": rm["code"],
                "product_name": rm["name"],
                "product_type": "Raw",
                "uom": rm["uom"],
                "category": "Belt Components",
            }).insert(ignore_permissions=True)
        # Ensure stock in Raw stage
        current_stk = flt(frappe.db.get_value("Inventory", {"product": rm["code"], "stage": "Raw"}, "stock"))
        if current_stk < 100:
            inv_name = frappe.db.get_value("Inventory", {"product": rm["code"], "stage": "Raw"}, "name")
            if not inv_name:
                inv_name = frappe.get_doc({
                    "doctype": "Inventory",
                    "product": rm["code"],
                    "stage": "Raw",
                    "stock": 0,
                    "total_amount": 0,
                    "unit_price": 0
                }).insert(ignore_permissions=True).name
            post([{"product": rm["code"], "stage": "Raw", "qty": rm["initial_stock"], "unit_price": rm["price"]}], "Inventory", inv_name)

    print("[✓] Raw materials created and stock initialized in Raw inventory.")

    # 3. Create Roll Semi-Finished Product (Stage 1 independent product)
    roll_code = "ROLL-CANVAS-500"
    if not frappe.db.exists("Product", roll_code):
        frappe.get_doc({
            "doctype": "Product",
            "product_code": roll_code,
            "product_name": "Canvas Rubber Roll 500mm",
            "product_type": "Semi",
            "total_steps": 1,
            "uom": "Nos",
            "category": "Belt Components",
        }).insert(ignore_permissions=True)

    # Create Roll BOM
    if not frappe.db.exists("BOM", roll_code):
        frappe.get_doc({
            "doctype": "BOM",
            "product": roll_code,
            "total_steps": 1,
            "stage1_items": [
                {"product": "RAW-RUBBER-BLK", "per_unit_utilization": 5.0}, # 5 kg @ 200 = 1000
                {"product": "RAW-CORD-CANVAS", "per_unit_utilization": 4.0}, # 4 m @ 50 = 200 -> total 1200 / roll
            ]
        }).insert(ignore_permissions=True)

    print(f"[✓] Roll product {roll_code} and Stage 1 BOM created.")

    # 4. Execute Stage 1 Batch for Roll Creation
    s1_batch = frappe.get_doc({
        "doctype": "Stage 1 Batch",
        "product": roll_code,
        "quantity": 10,
        "weight_per_piece": 9.0,
        "rejection_percent": 0.0,
        "items": [
            {"product": "RAW-RUBBER-BLK", "per_unit_utilization": 5.0, "actual_utilization": 50.0},
            {"product": "RAW-CORD-CANVAS", "per_unit_utilization": 4.0, "actual_utilization": 40.0},
        ]
    })
    s1_batch.insert(ignore_permissions=True)
    s1_batch.complete()
    frappe.db.commit()

    roll_s1_stock = flt(frappe.db.get_value("Inventory", {"product": roll_code, "stage": "Stage 1"}, "stock"))
    roll_s1_price = inventory_price(roll_code, "Stage 1")
    print(f"[✓] Stage 1 Batch completed: {s1_batch.name}")
    print(f"    Roll stock in Stage 1: {roll_s1_stock} rolls, Unit Price: ₹{roll_s1_price:.2f}/roll")
    assert roll_s1_stock >= 10, "Roll stock in Stage 1 should be at least 10"
    assert roll_s1_price > 0, "Roll unit price in Stage 1 should be > 0"

    # 5. Create Finished Belt Product
    belt_code = "BELT-GROMMED-800"
    if not frappe.db.exists("Product", belt_code):
        frappe.get_doc({
            "doctype": "Product",
            "product_code": belt_code,
            "product_name": "Grommed Heavy Duty Belt 800mm",
            "product_type": "Finished",
            "finished_good_type": "Belt",
            "band_type": "Grommed",
            "belt_length": 800,
            "belt_width": 40,
            "hole": 6,
            "total_steps": 3,
            "uom": "Nos",
            "category": "Belt Components",
        }).insert(ignore_permissions=True)

    if not frappe.db.exists("Charge", "Punching Labour"):
        frappe.get_doc({"doctype": "Charge", "charge_name": "Punching Labour"}).insert(ignore_permissions=True)

    # Create Belt BOM
    if not frappe.db.exists("BOM", belt_code):
        frappe.get_doc({
            "doctype": "BOM",
            "product": belt_code,
            "total_steps": 3,
            "stage2_items": [
                {"product": roll_code, "ratio": 4.0}, # Roll consumed = (size * qty) / 4
            ],
            "stage3_items": [
                {"product": "RAW-RIVET-M4", "calculation_type": "Hole", "ratio": 2.0}, # 2 rivets per hole
            ],
            "stage3_charges": [
                {"charge": "Punching Labour", "per_unit_price": 20.0}
            ]
        }).insert(ignore_permissions=True)

    print(f"[✓] Belt product {belt_code} and decoupled BOM created.")

    # 6. Test get_stage_rows API for Stage 2 (Belt sizing)
    s2_rows = get_stage_rows(product=belt_code, qty=40, stage=2, size=2)
    print(f"[✓] API get_stage_rows(stage=2, size=2, qty=40):")
    assert len(s2_rows["items"]) == 1, "Should have 1 item (Roll product)"
    roll_item = s2_rows["items"][0]
    print(f"    Consumed: {roll_item['product']}, per_unit: {roll_item['per_unit_utilization']}, total: {roll_item['total_utilization']}, unit_price: ₹{roll_item['unit_price']:.2f}")
    assert roll_item["product"] == roll_code, f"Should consume {roll_code}"
    # utilization: (size * qty) / ratio = (2 * 40) / 4 = 20 rolls
    assert flt(roll_item["total_utilization"]) == 20.0, f"Expected 20 rolls used, got {roll_item['total_utilization']}"

    # 7. Execute Stage 2 Batch
    initial_roll_stock = inventory_price(roll_code, "Stage 1")
    s2_batch = frappe.get_doc({
        "doctype": "Stage 2 Batch",
        "product": belt_code,
        "quantity": 40,
        "size": 2,
        "rejection_percent": 0.0,
        "items": [
            {
                "product": roll_code,
                "ratio": 4.0,
                "source_stage": "Stage 1",
                "per_unit_utilization": 0.5,
                "total_utilization": 20.0,
                "actual_utilization": 20.0,
            }
        ]
    })
    s2_batch.insert(ignore_permissions=True)
    s2_batch.complete()
    frappe.db.commit()

    belt_s2_stock = flt(frappe.db.get_value("Inventory", {"product": belt_code, "stage": "Stage 2"}, "stock"))
    belt_s2_cost = inventory_price(belt_code, "Stage 2")
    print(f"[✓] Stage 2 Batch completed: {s2_batch.name}")
    print(f"    Belt stock in Stage 2: {belt_s2_stock} belts, Unit Cost: ₹{belt_s2_cost:.2f}/belt")
    assert belt_s2_stock >= 40, "Belt stock in Stage 2 should be at least 40"
    assert belt_s2_cost > 0, "Belt Stage 2 unit cost should be > 0"

    # 8. Test get_stage_rows API for Stage 3 (Punching & Finishing)
    s3_rows = get_stage_rows(product=belt_code, qty=40, stage=3)
    print(f"[✓] API get_stage_rows(stage=3, qty=40):")
    # Carried row + Rivet row
    assert len(s3_rows["items"]) >= 2, "Should have carried Belt + Rivet item"
    carried_row = next(r for r in s3_rows["items"] if r.get("is_carried_in"))
    rivet_row = next(r for r in s3_rows["items"] if r["product"] == "RAW-RIVET-M4")
    print(f"    Carried: {carried_row['product']}, unit_price: ₹{carried_row['unit_price']:.2f}")
    # Rivets: qty * hole * ratio = 40 * 6 * 2 = 480 rivets
    print(f"    Component: {rivet_row['product']}, total: {rivet_row['total_utilization']}, unit_price: ₹{rivet_row['unit_price']:.2f}")
    assert flt(rivet_row["total_utilization"]) == 480.0, f"Expected 480 rivets, got {rivet_row['total_utilization']}"

    # 9. Execute Stage 3 Batch
    s3_batch = frappe.get_doc({
        "doctype": "Stage 3 Batch",
        "product": belt_code,
        "quantity": 40,
        "rejection_percent": 0.0,
        "items": [
            {
                "is_carried_in": 1,
                "product": belt_code,
                "per_unit_utilization": 1.0,
                "actual_utilization": 40.0,
                "source_stage": "Stage 2",
            },
            {
                "is_carried_in": 0,
                "product": "RAW-RIVET-M4",
                "calculation_type": "Hole",
                "ratio": 2.0,
                "per_unit_utilization": 12.0, # 6 holes * 2 ratio
                "actual_utilization": 480.0,
                "source_stage": "Raw",
            }
        ]
    })
    s3_batch.insert(ignore_permissions=True)
    s3_batch.complete()
    frappe.db.commit()

    belt_s3_stock = flt(frappe.db.get_value("Inventory", {"product": belt_code, "stage": "Stage 3"}, "stock"))
    belt_s3_cost = inventory_price(belt_code, "Stage 3")
    print(f"[✓] Stage 3 Batch completed: {s3_batch.name}")
    print(f"    Belt stock in Stage 3: {belt_s3_stock} belts, Unit Cost: ₹{belt_s3_cost:.2f}/belt")
    assert belt_s3_stock >= 40, "Belt stock in Stage 3 should be at least 40"
    assert belt_s3_cost > belt_s2_cost, "Finished unit cost should include component and carried costs"

    # 10. Verify get_finished_cost API
    fin_costs = get_finished_cost()
    print(f"[✓] API get_finished_cost() result for {belt_code}: {fin_costs.get(belt_code)}")
    assert belt_code in fin_costs, f"{belt_code} should appear in finished costs"
    assert fin_costs[belt_code]["unit_price"] == belt_s3_cost, "Finished cost should match Stage 3 unit cost"

    # 11. Verify get_inventory_bifurcation API
    bif = get_inventory_bifurcation(belt_code)
    print(f"[✓] API get_inventory_bifurcation() completed for {belt_code}")
    assert any(belt_code in k for k in bif.keys()), "Should have bifurcation entries for belt"
    for k, v in bif.items():
        if belt_code in k:
            print(f"    Stage: {v['stage']}, Unit Price: ₹{v['unit_price']:.2f}, Components: {[c['name'] for c in v['components']]}")

    print("=" * 60)
    print("ALL BELT PRODUCTION FLOW AND PRICING TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
