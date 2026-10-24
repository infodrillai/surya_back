"""The ONLY writer of Stock Ledger Entry and Inventory.

Inventory is keyed by product + stage (Raw, Stage 1, Stage 2, Finished). Receipts use weighted
average; issues are valued at the current average; negative stock is blocked unless the product
allows it. Runs inside the request transaction, so a failure rolls everything back.
"""
import frappe
from frappe import _
from frappe.utils import flt, now_datetime

EPS = 1e-9
SQL_ROW = "select name, stock, total_amount, unit_price from `tabInventory` where product=%s and stage=%s for update"


def inventory_price(product, stage):
    return flt(frappe.db.get_value("Inventory", {"product": product, "stage": stage}, "unit_price"))


def _locked_row(product, stage):
    rows = frappe.db.sql(SQL_ROW, (product, stage), as_dict=True)
    if rows:
        return rows[0]
    try:
        frappe.get_doc(
            {"doctype": "Inventory", "product": product, "stage": stage, "stock": 0, "total_amount": 0, "unit_price": 0}
        ).insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:  # another worker created it first
        pass
    return frappe.db.sql(SQL_ROW, (product, stage), as_dict=True)[0]


def _commit(row, product, stage, d_qty, d_value, price, ref_dt, ref_name, is_reversal=0, posting_datetime=None):
    stock = flt(row.stock) + d_qty
    total = flt(row.total_amount) + d_value
    if abs(stock) < EPS:
        stock, total = 0, 0
    unit = total / stock if stock else flt(row.unit_price)
    frappe.db.set_value(
        "Inventory", row.name, {"stock": stock, "total_amount": total, "unit_price": unit}, update_modified=False
    )
    frappe.get_doc(
        {
            "doctype": "Stock Ledger Entry",
            "product": product,
            "stage": stage,
            "posting_datetime": posting_datetime or now_datetime(),
            "qty_in": d_qty if d_qty > 0 else 0,
            "qty_out": -d_qty if d_qty < 0 else 0,
            "unit_price": price,
            "value": d_value,
            "reference_doctype": ref_dt,
            "reference_name": ref_name,
            "is_reversal": is_reversal,
        }
    ).insert(ignore_permissions=True)


def post(entries, ref_dt, ref_name, posting_datetime=None):
    """entries: [{product, stage, qty (+in / -out), unit_price (receipts only), posting_datetime (optional)}]"""
    for e in sorted(entries, key=lambda x: (x["product"], x["stage"], x["qty"] > 0)):  # stable lock order
        qty = flt(e["qty"])
        if abs(qty) < EPS:
            continue
        row = _locked_row(e["product"], e["stage"])
        pdt = e.get("posting_datetime") or posting_datetime
        if qty > 0:
            price = flt(e.get("unit_price"))
            _commit(row, e["product"], e["stage"], qty, qty * price, price, ref_dt, ref_name, posting_datetime=pdt)
        else:
            out = -qty
            if out > flt(row.stock) + EPS and not frappe.db.get_value("Product", e["product"], "allow_negative_stock"):
                frappe.throw(
                    _("Not enough {0} stock of {1}: available {2}, needed {3}").format(
                        e["stage"], e["product"], flt(row.stock, 4), flt(out, 4)
                    ),
                    title=_("Insufficient stock"),
                )
            price = flt(row.total_amount) / flt(row.stock) if flt(row.stock) > EPS else flt(row.unit_price)
            _commit(row, e["product"], e["stage"], qty, -out * price, price, ref_dt, ref_name, posting_datetime=pdt)


def reverse(ref_dt, ref_name):
    """Reopen: post reversing entries. Blocked if later movements depend on this document."""
    sles = frappe.get_all(
        "Stock Ledger Entry",
        filters={"reference_doctype": ref_dt, "reference_name": ref_name, "is_reversal": 0, "is_reversed": 0},
        fields=["name", "product", "stage", "qty_in", "qty_out", "unit_price", "value", "creation"],
        order_by="creation desc, name desc",
    )
    for s in sles:
        later = frappe.db.exists(
            "Stock Ledger Entry",
            {"product": s.product, "stage": s.stage, "creation": (">", s.creation), "reference_name": ("!=", ref_name)},
        )
        if later:
            frappe.throw(
                _("Cannot reopen: later stock movements exist for {0} ({1}). Reopen those documents first.").format(
                    s.product, s.stage
                )
            )
    for s in sles:
        row = _locked_row(s.product, s.stage)
        d_qty = -(flt(s.qty_in) - flt(s.qty_out))
        if flt(row.stock) + d_qty < -EPS:
            frappe.throw(_("Cannot reopen: stock of {0} ({1}) would go negative.").format(s.product, s.stage))
        _commit(row, s.product, s.stage, d_qty, -flt(s.value), flt(s.unit_price), ref_dt, ref_name, is_reversal=1)
        frappe.db.set_value("Stock Ledger Entry", s.name, "is_reversed", 1, update_modified=False)
