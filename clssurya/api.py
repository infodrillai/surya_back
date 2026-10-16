import frappe
from frappe import _
from frappe.utils import cint, flt

from clssurya.constants import COMPLETABLE, MASTERS
from clssurya.utils.base import is_admin
from clssurya.utils.stock_service import inventory_price
from clssurya.utils.versions import get_versions

ACTIONS = {
    **{dt: {"complete", "reopen"} for dt in COMPLETABLE},
    "Quotation": {"revise", "make_sales_order"},
    "Sales Order": {"approve"},
}


def _readable_masters():
    return [dt for dt in MASTERS if frappe.has_permission(dt, "read")]


@frappe.whitelist()
def get_csrf_token():
    return frappe.sessions.get_csrf_token()


@frappe.whitelist()
def me():
    user = frappe.session.user
    return {
        "user": user,
        "full_name": frappe.utils.get_fullname(user),
        "roles": frappe.get_roles(user),
        "is_admin": is_admin(user),
        "company_state": frappe.conf.get("company_state") or "Gujarat",
    }


@frappe.whitelist()
def get_master_versions():
    versions = get_versions()
    return {dt: int(versions.get(dt, 0)) for dt in _readable_masters()}


@frappe.whitelist()
def get_masters(only=None):
    allowed = _readable_masters()
    names = [d for d in (frappe.parse_json(only) if only else allowed) if d in allowed]
    versions = get_versions()
    data = {}
    for dt in names:
        if dt == "BOM":
            data[dt] = [frappe.get_doc("BOM", n).as_dict() for n in frappe.get_all("BOM", pluck="name")]
        else:
            data[dt] = frappe.get_all(dt, fields=["*"], limit_page_length=0)
    return {"data": data, "versions": {dt: int(versions.get(dt, 0)) for dt in names}}


@frappe.whitelist()
def get_stage_rows(product, qty, stage):
    """BOM rows for a batch: per-unit utilization, total utilization, amount, per-unit amount."""
    if not frappe.has_permission(f"Stage {cint(stage)} Batch", "read"):
        raise frappe.PermissionError
    stage, qty = cint(stage), flt(qty)
    bom = frappe.get_doc("BOM", product)
    if cint(bom.total_steps) < stage:
        frappe.throw(_("{0} has only {1} step(s) in its BOM.").format(product, bom.total_steps))

    def row(**kw):
        per, price = flt(kw["per_unit_utilization"]), flt(kw["unit_price"])
        total = per * qty
        return {**kw, "total_utilization": total, "actual_utilization": total, "amount": total * price,
                "per_unit_amount": per * price, "actual_amount": total * price, "extra_cost": flt(kw.get('extra_cost', 0))}

    out = {"items": [], "charges": [], "wastage_product": None}
    if stage > 1:
        prev = "Stage 1" if stage == 2 else "Stage 2"
        out["items"].append(row(is_carried_in=1, process=None, product=product, per_unit_utilization=1,
                                unit_price=inventory_price(product, prev)))
    if stage == 1:
        for r in bom.stage1_items:
            out["wastage_product"] = out["wastage_product"] or r.wastage_product
            out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                    per_unit_utilization=r.per_unit_utilization, unit_price=inventory_price(r.product, "Raw")))
    elif stage == 2:
        for r in bom.stage2_items:
            out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                    per_unit_utilization=r.per_unit_utilization, unit_price=inventory_price(r.product, "Raw")))
    else:
        out["charges"] = [{"charge": c.charge, "per_unit_price": c.per_unit_price, "amount": flt(c.per_unit_price) * qty}
                          for c in bom.stage3_charges]
    return out


@frappe.whitelist()
def get_stock_by_stage(product=None):
    if not frappe.has_permission("Inventory", "read"):
        raise frappe.PermissionError
    filters = {"product": product} if product else {}
    return frappe.get_all("Inventory", filters=filters, fields=["product", "stage", "stock", "total_amount", "unit_price"])


@frappe.whitelist()
def get_finished_cost():
    """Finished stock and production cost per unit. Open to Sales (they cannot read the ledger)."""
    rows = frappe.get_all("Inventory", filters={"stage": "Finished"}, fields=["product", "stock", "unit_price"])
    return {r.product: {"stock": r.stock, "unit_price": r.unit_price} for r in rows}


@frappe.whitelist(methods=["POST"])
def run_action(doctype, name, action):
    if action not in ACTIONS.get(doctype, set()):
        frappe.throw(_("Action {0} is not allowed on {1}.").format(action, doctype), frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    result = getattr(doc, action)()
    return {"name": name, "result": result}
