"""Pure costing formulas (no Frappe import) - mirrored in frontend/src/lib/formulas.js.

Base = carried + added;  Rejection = Base x rejection%;  Total = Base + Rejection;  Unit = Total / qty
"""
from decimal import ROUND_HALF_UP, Decimal


def money(value):
    """The one money-rounding rule (2 dp, half up). Used for display only."""
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def stage_totals(carried, added, rejection_percent, qty, tooling=0, rejection_per_piece=0):
    base = (carried or 0) + (added or 0) + (tooling or 0)
    # a per-piece amount overrides the percentage when entered
    if (rejection_per_piece or 0) > 0:
        rejection = rejection_per_piece * (qty or 0)
    else:
        rejection = base * (rejection_percent or 0) / 100
    total = base + rejection
    # good_qty = accepted pieces (total minus rejected); unit cost is spread over them
    if (rejection_percent or 0) > 0:
        good_qty = (qty or 0) * (1 - (rejection_percent or 0) / 100)
    else:
        good_qty = qty or 0
    effective_qty = good_qty if good_qty > 0 else (qty or 0)
    return {
        "base": base,
        "rejection_amount": rejection,
        "batch_total": total,
        "unit_cost": total / effective_qty if effective_qty else 0,
        "unit_cost_without_rejection": base / (qty or 1) if qty else 0,
    }


def stage1_wastage(material_used, output_qty, weight_per_piece):
    return round((material_used or 0) - (output_qty or 0) * (weight_per_piece or 0), 9)


def split_gst(amount, gst_percent, vendor_state, company_state):
    tax = (amount or 0) * (gst_percent or 0) / 100
    if (vendor_state or "").strip().lower() == (company_state or "").strip().lower():
        return {"cgst": tax / 2, "sgst": tax / 2, "igst": 0}
    return {"cgst": 0, "sgst": 0, "igst": tax}


def allocate_extra(amounts, extra):
    """Landed cost: spread extra charges across rows by value."""
    total = sum(amounts)
    return [(extra or 0) * a / total if total else 0 for a in amounts]
