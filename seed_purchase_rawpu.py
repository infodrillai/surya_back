"""
Seed script – create and complete a Purchase Entry for RAW-PU at ₹471.25
so that Stage 2 batch for Shuttle Roller P shows unit cost ≈ 50.589
with 4.599% rejection (qty 200).

Run with:
    cd /home/dlip/dev/frappe-bench
    bench --site <your-site> execute seed_purchase_rawpu.run
"""

import frappe
from frappe.utils import nowdate


def run():
    # ------------------------------------------------------------------ #
    # CONFIGURE THESE to match your actual Vendor / Product names         #
    # ------------------------------------------------------------------ #
    VENDOR        = "V-001"          # ← change to your real vendor name
    PRODUCT       = "RAW-PU"         # product code for Polyurethane
    NEW_RATE      = 471.25           # target landed rate (was ₹465)
    PURCHASE_QTY  = 100              # qty large enough to shift weighted avg
    GST_PERCENT   = 18               # adjust if different
    BILL_NO       = "SEED-RAWPU-001"
    # ------------------------------------------------------------------ #

    if frappe.db.exists("Purchase Entry", {"bill_no": BILL_NO}):
        print(f"Already exists ({BILL_NO}) — skipping.")
        return

    pe = frappe.new_doc("Purchase Entry")
    pe.vendor        = VENDOR
    pe.posting_date  = nowdate()
    pe.bill_no       = BILL_NO
    pe.extra_charges = 0

    pe.append("items", {
        "product":      PRODUCT,
        "quantity":     PURCHASE_QTY,
        "rate":         NEW_RATE,
        "gst_percent":  GST_PERCENT,
        "extra_charge": 0,
    })

    pe.insert()
    print(f"Created  : {pe.name}")

    pe.is_completed = 1
    pe.save()
    print(f"Completed: {pe.name}")
    print(f"RAW-PU weighted-avg now ≈ ₹{NEW_RATE}")
    print()
    print("Next: open a new Stage 2 batch → Shuttle Roller P, qty 200, rejection 4.599%")
    print("      Unit cost should show ≈ 50.589")
    frappe.db.commit()
