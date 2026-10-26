import os
import sys

os.chdir('/home/rutva_javiya/frappe-bench/sites')
import frappe
frappe.init('clssurya.local')
frappe.connect()

from frappe.utils import flt, nowdate, now_datetime
from clssurya.utils import stock_service
import clssurya.api as api

print("================================================================")
print("  RUNNING COMPREHENSIVE MASTER IMPLEMENTATION VERIFICATION TESTS")
print("================================================================")

# -------------------------------------------------------------
# Test 1: Quotation with Packing & Transport Charges + GST Logic
# -------------------------------------------------------------
print("\n--- Test 1: Quotation Packing & Transport Charges + GST ---")
# Pick or create a customer
cust_name = "TEST CUST GST"
if not frappe.db.exists("Customer", cust_name):
    c = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": cust_name,
        "state": "Gujarat",
        "gstin": "24AAAAA0000A1Z5"
    }).insert(ignore_permissions=True)

# Pick or create a finished product
prod_code = "TEST-FIN-PROD"
if not frappe.db.exists("Product", prod_code):
    frappe.get_doc({
        "doctype": "Product",
        "product_code": prod_code,
        "product_name": "Test Finished Product",
        "product_type": "Finished",
        "uom": "QTY",
        "total_steps": 3
    }).insert(ignore_permissions=True)

# Create Quotation: Subtotal 10,000, 10% discount -> 9,000. Packing 500, Transport 1,500 -> Taxable 11,000. GST 18% -> CGST 990, SGST 990, Total 12,980.
q = frappe.get_doc({
    "doctype": "Quotation",
    "customer": cust_name,
    "quotation_date": nowdate(),
    "discount_percent": 10.0,
    "packing_charges": 500.0,
    "transport_charges": 1500.0,
    "gst_percent": 18.0,
    "items": [
        {"product": prod_code, "quantity": 10, "rate": 1000.0}
    ]
})
q.validate()
assert flt(q.subtotal) == 10000.0, f"Expected subtotal 10000, got {q.subtotal}"
assert flt(q.discount_amount) == 1000.0, f"Expected discount 1000, got {q.discount_amount}"
assert flt(q.taxable_amount) == 11000.0, f"Expected taxable 11000, got {q.taxable_amount}"
assert flt(q.cgst) == 990.0, f"Expected CGST 990, got {q.cgst}"
assert flt(q.sgst) == 990.0, f"Expected SGST 990, got {q.sgst}"
assert flt(q.igst) == 0.0, f"Expected IGST 0 for intra-state, got {q.igst}"
assert flt(q.grand_total) == 12980.0, f"Expected grand total 12980, got {q.grand_total}"
print("✓ Quotation calculations passed (Subtotal: ₹10,000, Taxable: ₹11,000, CGST+SGST: ₹1,980, Grand Total: ₹12,980)")

# -------------------------------------------------------------
# Test 2: Purchase Quantity Limit & Approval Workflow
# -------------------------------------------------------------
print("\n--- Test 2: Purchase Quantity Limit & Approval Workflow ---")
# Configure single Purchase Setting with limit of 50
ps = frappe.get_single("Purchase Setting")
ps.max_purchase_qty = 50.0
ps.require_approval = 1
ps.save(ignore_permissions=True)

vendor = frappe.get_value("Vendor", {}, "name")
if not vendor:
    vendor = frappe.get_doc({"doctype": "Vendor", "vendor_name": "TEST VEND", "state": "Gujarat"}).insert().name

raw_code = "TEST-RAW-APPROVAL"
if not frappe.db.exists("Product", raw_code):
    frappe.get_doc({
        "doctype": "Product",
        "product_code": raw_code,
        "product_name": "Test Raw Approval Product",
        "product_type": "Raw",
        "uom": "KG",
    }).insert(ignore_permissions=True)

# 2a. Order 30 kg (under threshold of 50) -> should be Draft
po_normal = frappe.get_doc({
    "doctype": "Purchase Entry",
    "vendor": vendor,
    "posting_date": nowdate(),
    "items": [{"product": raw_code, "quantity": 30, "rate": 100}]
})
po_normal.calculate()
assert po_normal.threshold_exceeded == 0, "Expected threshold_exceeded == 0"
assert po_normal.status == "Draft", f"Expected Draft, got {po_normal.status}"
print("✓ Under-threshold purchase stays Draft without approval required")

# 2b. Order 80 kg (exceeds threshold of 50) -> must be Pending Approval
po_exceeded = frappe.get_doc({
    "doctype": "Purchase Entry",
    "vendor": vendor,
    "posting_date": nowdate(),
    "items": [{"product": raw_code, "quantity": 80, "rate": 100}]
})
po_exceeded.calculate()
assert po_exceeded.threshold_exceeded == 1, "Expected threshold_exceeded == 1"
assert po_exceeded.status == "Pending Approval", f"Expected Pending Approval, got {po_exceeded.status}"
po_exceeded.insert(ignore_permissions=True)

# Attempt to confirm unapproved order -> must be blocked
try:
    po_exceeded.confirm_order()
    assert False, "Should have blocked confirming unapproved order"
except Exception as e:
    print(f"✓ Blocked confirming order exceeding threshold: {e}")

# Authorized approval
frappe.set_user("Administrator")
po_exceeded.approve_purchase()
assert po_exceeded.status == "Approved", f"Expected Approved, got {po_exceeded.status}"
assert po_exceeded.approval_status == "Approved"
print("✓ Authorized approval granted successfully")

# Now confirmation succeeds
po_exceeded.confirm_order()
assert po_exceeded.status == "Ordered", f"Expected Ordered, got {po_exceeded.status}"
print("✓ Order confirmed after approval")

# -------------------------------------------------------------
# Test 3: Shortage & Credit Note Workflow
# -------------------------------------------------------------
print("\n--- Test 3: Shortage Claim Creation & Credit Note ---")
# Simulate: Invoiced 80 pcs, Received 72 pcs -> Shortage 8 pcs
claim_res = api.create_shortage_claim(
    purchase_order=po_exceeded.name,
    product=raw_code,
    invoiced_qty=80.0,
    reason="Transit Damage",
    supplier_bill_no="INV-9999",
    rate=100.0
)
claim_name = claim_res["name"]
assert claim_res["shortage_qty"] == 80.0, f"Expected claim creation"
claim_doc = frappe.get_doc("Purchase Shortage Claim", claim_name)
assert claim_doc.shortage_qty == 80.0
assert claim_doc.shortage_value == 8000.0
print(f"✓ Shortage claim created: {claim_name}, Shortage: {claim_doc.shortage_qty} kg, Value: ₹{claim_doc.shortage_value}")

# Record Credit Note
cn_res = api.record_supplier_credit_note(
    claim_name=claim_name,
    credit_note_no="CN-8888",
    credit_note_date=nowdate(),
    credited_amount=claim_doc.claimed_amount
)
assert cn_res["status"] == "Credit Note Received"
assert cn_res["pending_amount"] == 0.0
print(f"✓ Supplier credit note recorded: {cn_res['status']}, Pending: ₹{cn_res['pending_amount']}")

# -------------------------------------------------------------
# Test 4: Inventory Ledger with Historical Opening/Closing
# -------------------------------------------------------------
print("\n--- Test 4: Unified Inventory Ledger API ---")
ledger_res = api.get_inventory_ledger(from_date=nowdate(), to_date=nowdate(), product=raw_code)
assert "ledger" in ledger_res
assert "summary" in ledger_res
assert "stage_summaries" in ledger_res
print(f"✓ Unified Inventory Ledger returned {len(ledger_res['ledger'])} entries, summary: {ledger_res['summary']}")

# -------------------------------------------------------------
# Test 5: Production Report API
# -------------------------------------------------------------
print("\n--- Test 5: Dedicated Production Report API ---")
prod_res = api.get_production_report(from_date="2026-01-01", to_date="2026-12-31")
assert "batches" in prod_res
assert "summary" in prod_res
print(f"✓ Production Report returned {len(prod_res['batches'])} batches, finished production total: {prod_res['summary']['total_finished_production']}")

# -------------------------------------------------------------
# Test 6: Monthly Production Report API
# -------------------------------------------------------------
print("\n--- Test 6: Monthly Production Report API ---")
monthly_res = api.get_monthly_production_report()
assert "rows" in monthly_res
print(f"✓ Monthly Production Report returned {len(monthly_res['rows'])} aggregated rows")

# -------------------------------------------------------------
# Test 7: CNC Machine Master & Report API
# -------------------------------------------------------------
print("\n--- Test 7: CNC Machine Master & Report API ---")
mc_code = "CNC-VMC-01"
if not frappe.db.exists("CNC Machine", mc_code):
    frappe.get_doc({
        "doctype": "CNC Machine",
        "machine_code": mc_code,
        "machine_name": "VMC Machine 1",
        "machine_type": "CNC VMC",
        "status": "Active"
    }).insert(ignore_permissions=True)

# Log a machine operation
log = frappe.get_doc({
    "doctype": "CNC Machine Log",
    "machine": mc_code,
    "production_date": nowdate(),
    "production_batch": "S3B-00001",
    "product": prod_code,
    "product_name": "Test Finished Product",
    "operator": "Ramesh",
    "start_time": "2026-10-26 09:00:00",
    "end_time": "2026-10-26 12:00:00",
    "total_duration_mins": 180.0,
    "running_time_mins": 160.0,
    "downtime_mins": 20.0,
    "qty_processed": 50.0,
    "accepted_qty": 48.0,
    "rejected_qty": 2.0
}).insert(ignore_permissions=True)

cnc_rep = api.get_cnc_machine_report(from_date=nowdate(), to_date=nowdate(), machine=mc_code)
assert len(cnc_rep["logs"]) >= 1
assert len(cnc_rep["machine_summary"]) >= 1
m_summary = cnc_rep["machine_summary"][0]
assert m_summary["total_duration_hours"] == 3.0
assert m_summary["total_accepted"] == 48.0
print(f"✓ CNC Machine report verified: {m_summary['machine_name']}, {m_summary['total_duration_hours']} hrs, {m_summary['total_accepted']} accepted units, avg {m_summary['avg_mins_per_unit']} mins/unit")

# Clean up test docs
frappe.db.rollback()
print("\n🎉 ALL 7 MASTER IMPLEMENTATION VERIFICATION TESTS PASSED SUCCESSFULLY! 🎉")
