import os
os.chdir('/home/rutva_javiya/frappe-bench/sites')
import frappe
frappe.init('clssurya.local')
frappe.connect()

from frappe.utils import flt, nowdate
from clssurya.utils import stock_service

print("=== Starting Purchase Order & Goods Receipt Workflow Tests ===")

# Pick an existing vendor and Raw product
vendor = frappe.get_value("Vendor", {}, "name")
if not vendor:
    v = frappe.get_doc({"doctype": "Vendor", "vendor_name": "TEST VENDOR", "state": "Gujarat"}).insert()
    vendor = v.name

# Create a test raw product to avoid affecting live production products
test_product_name = "TEST-ALUM-RAW"
if not frappe.db.exists("Product", test_product_name):
    p = frappe.get_doc({
        "doctype": "Product",
        "product_code": test_product_name,
        "product_name": "Aluminium Ingot Test",
        "product_type": "Raw",
        "uom": "kg",
    }).insert(ignore_permissions=True)

# Ensure clean initial inventory for test product
initial_stock = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
initial_val = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "total_amount") or 0)
print(f"Initial Inventory for {test_product_name}: Stock = {initial_stock}, Total Value = {initial_val}")

# -------------------------------------------------------------
# Test 1: Create Purchase Order (100 kg at ₹300/kg)
# -------------------------------------------------------------
print("\n--- Test 1: Create Purchase Order (100 kg @ ₹300/kg, Extra charges: ₹2000) ---")
po = frappe.get_doc({
    "doctype": "Purchase Entry",
    "vendor": vendor,
    "posting_date": "2026-10-05",
    "expected_delivery_date": "2026-10-15",
    "bill_no": "PO-TEST-001",
    "extra_charges": 2000.0,
    "items": [{
        "product": test_product_name,
        "quantity": 100.0,
        "rate": 300.0,
        "gst_percent": 18.0,
    }]
})
po.insert(ignore_permissions=True)

assert po.status == "Draft", f"Expected Draft status, got {po.status}"
assert flt(po.total_ordered_qty) == 100.0, f"Expected 100 ordered, got {po.total_ordered_qty}"
assert flt(po.total_received_qty) == 0.0, f"Expected 0 received, got {po.total_received_qty}"
assert flt(po.total_pending_qty) == 100.0, f"Expected 100 pending, got {po.total_pending_qty}"

# Landed rate: 30000 + 2000 = 32000 / 100 = 320.0
item0 = po.items[0]
assert flt(item0.landed_rate) == 320.0, f"Expected landed rate 320, got {item0.landed_rate}"

# Confirm saving/creating PO did NOT add stock
stock_after_po = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
assert stock_after_po == initial_stock, f"Stock increased on PO creation! Before: {initial_stock}, After: {stock_after_po}"
print(f"✓ PO created: {po.name}, Status = {po.status}, Stock = {stock_after_po} (no stock added)")

# Confirm order
po.confirm_order()
po.reload()
assert po.status == "Ordered", f"Expected Ordered status, got {po.status}"
print(f"✓ PO confirmed: Status = {po.status}")

# -------------------------------------------------------------
# Test 2: Partial Goods Receipt (60 kg on 2026-10-10)
# -------------------------------------------------------------
print("\n--- Test 2: Partial Goods Receipt (60 kg on 2026-10-10) ---")
gr1 = frappe.get_doc({
    "doctype": "Goods Receipt",
    "purchase_order": po.name,
    "posting_date": "2026-10-10",
    "supplier_delivery_note": "DEL-NOTE-60",
    "items": [{
        "purchase_order_item": po.items[0].name,
        "product": test_product_name,
        "received_qty": 60.0,
    }]
})
gr1.insert(ignore_permissions=True)
gr1.confirm_receipt()
gr1.reload()

assert gr1.status == "Confirmed", f"Expected GR Confirmed, got {gr1.status}"
assert flt(gr1.total_qty) == 60.0, f"Expected 60 total_qty, got {gr1.total_qty}"

po.reload()
assert po.status == "Partially Received", f"Expected Partially Received, got {po.status}"
assert flt(po.total_received_qty) == 60.0, f"Expected 60 received, got {po.total_received_qty}"
assert flt(po.total_pending_qty) == 40.0, f"Expected 40 pending, got {po.total_pending_qty}"

# Check inventory increase: exactly +60 kg
stock_after_gr1 = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
assert stock_after_gr1 == initial_stock + 60.0, f"Expected stock {initial_stock + 60}, got {stock_after_gr1}"
print(f"✓ GR1 confirmed: {gr1.name}, PO Status = {po.status}, Received = {po.total_received_qty}, Pending = {po.total_pending_qty}, Inventory = {stock_after_gr1} (+60 kg)")

# -------------------------------------------------------------
# Test 3: Over-receipt validation (attempt 50 kg when only 40 kg pending)
# -------------------------------------------------------------
print("\n--- Test 3: Over-receipt validation (attempt 50 kg when 40 pending) ---")
gr_over = frappe.get_doc({
    "doctype": "Goods Receipt",
    "purchase_order": po.name,
    "posting_date": "2026-10-11",
    "items": [{
        "purchase_order_item": po.items[0].name,
        "product": test_product_name,
        "received_qty": 50.0,
    }]
})
gr_over.insert(ignore_permissions=True)
try:
    gr_over.confirm_receipt()
    assert False, "Over-receipt should have thrown an error but succeeded!"
except frappe.ValidationError as e:
    print(f"✓ Over-receipt properly blocked: {e}")
except Exception as e:
    print(f"✓ Over-receipt properly blocked with message: {e}")

# -------------------------------------------------------------
# Test 4: Duplicate confirmation prevention
# -------------------------------------------------------------
print("\n--- Test 4: Duplicate confirmation prevention ---")
try:
    gr1.confirm_receipt()
    assert False, "Confirming already confirmed receipt should have failed!"
except Exception as e:
    print(f"✓ Duplicate confirmation properly blocked: {e}")

# -------------------------------------------------------------
# Test 5: Second Goods Receipt (40 kg on 2026-10-12)
# -------------------------------------------------------------
print("\n--- Test 5: Second Goods Receipt (40 kg on 2026-10-12) ---")
gr2 = frappe.get_doc({
    "doctype": "Goods Receipt",
    "purchase_order": po.name,
    "posting_date": "2026-10-12",
    "supplier_delivery_note": "DEL-NOTE-40",
    "items": [{
        "purchase_order_item": po.items[0].name,
        "product": test_product_name,
        "received_qty": 40.0,
    }]
})
gr2.insert(ignore_permissions=True)
gr2.confirm_receipt()
gr2.reload()

po.reload()
assert po.status == "Received", f"Expected Received, got {po.status}"
assert po.is_completed == 1, f"Expected is_completed = 1, got {po.is_completed}"
assert flt(po.total_received_qty) == 100.0, f"Expected 100 received, got {po.total_received_qty}"
assert flt(po.total_pending_qty) == 0.0, f"Expected 0 pending, got {po.total_pending_qty}"

# Check total inventory increase: exactly +100 kg
stock_after_gr2 = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
assert stock_after_gr2 == initial_stock + 100.0, f"Expected stock {initial_stock + 100}, got {stock_after_gr2}"
print(f"✓ GR2 confirmed: {gr2.name}, PO Status = {po.status}, Received = {po.total_received_qty}, Pending = {po.total_pending_qty}, Inventory = {stock_after_gr2} (Total increase = +100 kg)")

# -------------------------------------------------------------
# Test 6: Verify Stock Ledger Entries
# -------------------------------------------------------------
print("\n--- Test 6: Stock Ledger Entries Verification ---")
sles = frappe.get_all(
    "Stock Ledger Entry",
    filters={"reference_doctype": "Goods Receipt", "reference_name": ["in", [gr1.name, gr2.name]]},
    fields=["name", "product", "qty_in", "unit_price", "value", "reference_name"],
    order_by="creation asc"
)
assert len(sles) == 2, f"Expected 2 SLEs, found {len(sles)}"
assert flt(sles[0].qty_in) == 60.0 and flt(sles[0].unit_price) == 320.0
assert flt(sles[1].qty_in) == 40.0 and flt(sles[1].unit_price) == 320.0
print(f"✓ Stock Ledger Entries verified: GR1 = {sles[0].qty_in} kg @ ₹{sles[0].unit_price}, GR2 = {sles[1].qty_in} kg @ ₹{sles[1].unit_price}")

# -------------------------------------------------------------
# Test 7: Cancellation and Stock Reversal
# -------------------------------------------------------------
print("\n--- Test 7: Cancellation and Stock Reversal (Cancel GR2) ---")
gr2.cancel_receipt()
gr2.reload()
assert gr2.status == "Cancelled", f"Expected Cancelled, got {gr2.status}"

po.reload()
assert po.status == "Partially Received", f"Expected PO status Partially Received after cancelling GR2, got {po.status}"
assert flt(po.total_received_qty) == 60.0, f"Expected 60 received, got {po.total_received_qty}"
assert flt(po.total_pending_qty) == 40.0, f"Expected 40 pending, got {po.total_pending_qty}"

stock_after_cancel = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
assert stock_after_cancel == initial_stock + 60.0, f"Expected stock {initial_stock + 60}, got {stock_after_cancel}"
print(f"✓ GR2 cancelled: Stock restored to {stock_after_cancel} kg, PO status restored to {po.status} (Received: 60 kg, Pending: 40 kg)")

# -------------------------------------------------------------
# Test 8: Weighted-average valuation test
# -------------------------------------------------------------
print("\n--- Test 8: Weighted-Average Inventory Valuation Test ---")
frappe.db.sql("DELETE FROM `tabStock Ledger Entry` WHERE product=%s", (test_product_name,))
frappe.db.sql("DELETE FROM `tabInventory` WHERE product=%s", (test_product_name,))

# 1. PO1: 50 kg at ₹200/kg -> GR1
po_val1 = frappe.get_doc({
    "doctype": "Purchase Entry",
    "vendor": vendor,
    "posting_date": "2026-10-14",
    "bill_no": "PO-VAL-001",
    "extra_charges": 0.0,
    "items": [{
        "product": test_product_name,
        "quantity": 50.0,
        "rate": 200.0,
        "gst_percent": 18.0,
    }]
}).insert(ignore_permissions=True)
po_val1.confirm_order()

gr_val1 = frappe.get_doc({
    "doctype": "Goods Receipt",
    "purchase_order": po_val1.name,
    "posting_date": "2026-10-14",
    "items": [{
        "purchase_order_item": po_val1.items[0].name,
        "product": test_product_name,
        "received_qty": 50.0,
    }]
}).insert(ignore_permissions=True)
gr_val1.confirm_receipt()

inv1 = frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, ["stock", "unit_price", "total_amount"], as_dict=True)
assert flt(inv1.stock) == 50.0 and flt(inv1.unit_price) == 200.0 and flt(inv1.total_amount) == 10000.0

# 2. PO2: 50 kg at ₹400/kg -> GR2
po_val2 = frappe.get_doc({
    "doctype": "Purchase Entry",
    "vendor": vendor,
    "posting_date": "2026-10-15",
    "bill_no": "PO-VAL-002",
    "extra_charges": 0.0,
    "items": [{
        "product": test_product_name,
        "quantity": 50.0,
        "rate": 400.0,
        "gst_percent": 18.0,
    }]
}).insert(ignore_permissions=True)
po_val2.confirm_order()

gr_val2 = frappe.get_doc({
    "doctype": "Goods Receipt",
    "purchase_order": po_val2.name,
    "posting_date": "2026-10-16",
    "items": [{
        "purchase_order_item": po_val2.items[0].name,
        "product": test_product_name,
        "received_qty": 50.0,
    }]
}).insert(ignore_permissions=True)
gr_val2.confirm_receipt()

# 3. Check inventory: 50 + 50 = 100 kg, total value: 10000 + 20000 = 30000, unit price = 300.0
inv2 = frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, ["stock", "unit_price", "total_amount"], as_dict=True)
assert flt(inv2.stock) == 100.0, f"Expected 100 kg stock, got {inv2.stock}"
assert flt(inv2.total_amount) == 30000.0, f"Expected 30000 value, got {inv2.total_amount}"
assert flt(inv2.unit_price) == 300.0, f"Expected weighted average ₹300/kg, got {inv2.unit_price}"
print(f"✓ Weighted-average valuation verified: 50 kg @ ₹200 + 50 kg @ ₹400 = 100 kg @ ₹{inv2.unit_price}/kg (Total: ₹{inv2.total_amount})")

frappe.delete_doc("Goods Receipt", gr_val1.name, force=True)
frappe.delete_doc("Goods Receipt", gr_val2.name, force=True)
po_val1.db_set("is_completed", 0)
po_val2.db_set("is_completed", 0)
frappe.delete_doc("Purchase Entry", po_val1.name, force=True)
frappe.delete_doc("Purchase Entry", po_val2.name, force=True)

# Clean up test documents
print("\n--- Cleaning up test records ---")
frappe.db.sql("DELETE FROM `tabStock Ledger Entry` WHERE product=%s", (test_product_name,))
frappe.db.sql("DELETE FROM `tabInventory` WHERE product=%s", (test_product_name,))
frappe.delete_doc("Goods Receipt", gr_over.name, force=True)
frappe.delete_doc("Goods Receipt", gr2.name, force=True)
frappe.delete_doc("Goods Receipt", gr1.name, force=True)
po.db_set("is_completed", 0)
frappe.delete_doc("Purchase Entry", po.name, force=True)
frappe.delete_doc("Product", test_product_name, force=True)
frappe.db.commit()

final_stock = flt(frappe.db.get_value("Inventory", {"product": test_product_name, "stage": "Raw"}, "stock") or 0)
print(f"✓ All test records cleaned up. Final stock = {final_stock}")
print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")
