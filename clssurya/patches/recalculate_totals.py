"""
Backfill grand_total for existing Quotation and Sales Order records
that were created before the field existed.
"""
import frappe
from frappe.utils import flt


def execute():
    # --- Quotations ---
    qtns = frappe.get_all("Quotation", filters={}, fields=["name"])
    print(f"Recalculating {len(qtns)} Quotations...")
    for q in qtns:
        try:
            doc = frappe.get_doc("Quotation", q.name)
            subtotal = sum(flt(r.quantity) * flt(r.rate) for r in doc.items)
            dp = flt(getattr(doc, "discount_percent", 0))
            gp = flt(getattr(doc, "gst_percent", 18))
            discount_amount = subtotal * dp / 100
            taxable_amount = max(0.0, subtotal - discount_amount)
            tax_amount = taxable_amount * gp / 100
            grand_total = taxable_amount + tax_amount
            frappe.db.set_value("Quotation", q.name, {
                "subtotal": subtotal,
                "discount_amount": discount_amount,
                "taxable_amount": taxable_amount,
                "tax_amount": tax_amount,
                "grand_total": grand_total,
            }, update_modified=False)
        except Exception as e:
            print(f"  SKIP {q.name}: {e}")
    print("Quotations done.")

    # --- Sales Orders ---
    sos = frappe.get_all("Sales Order", filters={}, fields=["name"])
    print(f"Recalculating {len(sos)} Sales Orders...")
    for s in sos:
        try:
            doc = frappe.get_doc("Sales Order", s.name)
            subtotal = sum(flt(r.quantity) * flt(r.rate) for r in doc.items)
            dp = flt(getattr(doc, "discount_percent", 0))
            gp = flt(getattr(doc, "gst_percent", 18))
            discount_amount = subtotal * dp / 100
            taxable_amount = max(0.0, subtotal - discount_amount)
            tax_amount = taxable_amount * gp / 100
            grand_total = taxable_amount + tax_amount
            frappe.db.set_value("Sales Order", s.name, {
                "subtotal": subtotal,
                "discount_amount": discount_amount,
                "taxable_amount": taxable_amount,
                "tax_amount": tax_amount,
                "grand_total": grand_total,
            }, update_modified=False)
        except Exception as e:
            print(f"  SKIP {s.name}: {e}")
    print("Sales Orders done.")

    # --- Dispatches ---
    dsps = frappe.get_all("Dispatch", filters={}, fields=["name", "sales_order"])
    print(f"Recalculating {len(dsps)} Dispatches...")
    for d in dsps:
        try:
            disp = frappe.get_doc("Dispatch", d.name)
            so = frappe.get_doc("Sales Order", disp.sales_order)
            so_items = {r.name: r for r in so.items}
            discount_percent = flt(getattr(so, "discount_percent", 0))
            gst_percent = flt(getattr(so, "gst_percent", 18))
            subtotal = 0.0
            for r in disp.items:
                so_line = so_items.get(r.order_item)
                rate = flt(so_line.rate) if so_line else flt(r.unit_cost)
                subtotal += flt(r.quantity) * rate
            discount_amount = subtotal * discount_percent / 100
            taxable_amount = max(0.0, subtotal - discount_amount)
            tax_amount = taxable_amount * gst_percent / 100
            grand_total = taxable_amount + tax_amount
            frappe.db.set_value("Dispatch", d.name, "grand_total", grand_total, update_modified=False)
        except Exception as e:
            print(f"  SKIP {d.name}: {e}")
    print("Dispatches done.")

    frappe.db.commit()
    print("All done. Commit OK.")
