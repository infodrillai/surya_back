import frappe
from frappe import _
from frappe.utils import cint, flt

from clssurya.constants import COMPLETABLE, MASTERS
from clssurya.utils.base import is_admin
from clssurya.utils.stock_service import inventory_price
from clssurya.utils.versions import get_versions

ACTIONS = {
    **{dt: {"complete", "reopen"} for dt in COMPLETABLE},
    "Purchase Entry": {"confirm_order", "cancel_order", "complete", "reopen"},
    "Goods Receipt": {"confirm_receipt", "cancel_receipt"},
    "Quotation": {"revise", "make_sales_order", "approve"},
    "Sales Order": {"approve", "reject", "cancel", "create_dispatch", "create_dispatch_from_sales_order", "linked_dispatches"},
    "Dispatch": {"confirm_dispatch", "cancel_dispatch", "complete", "reopen"},
    "Customer Return": {"confirm_return", "cancel_return"},
}


def _readable_masters():
    # Guest users should be able to read master data for demo purposes
    if frappe.session.user == "Guest":
        return MASTERS
    return [dt for dt in MASTERS if frappe.has_permission(dt, "read")]


@frappe.whitelist()
def get_csrf_token():
    return frappe.sessions.get_csrf_token()


@frappe.whitelist(allow_guest=True)
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


@frappe.whitelist(allow_guest=True)
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


@frappe.whitelist()
def get_inventory_bifurcation(product=None):
    """Calculates the charge and component bifurcation of total valuation for inventory."""
    if not frappe.has_permission("Inventory", "read"):
        raise frappe.PermissionError

    filters = {"product": product} if product else {}
    inv_rows = frappe.get_all("Inventory", filters=filters, fields=["name", "product", "stage", "stock", "total_amount", "unit_price"])

    results = {}
    default_prices = {
        "ALM": 450.0,
        "RAW-PU": 466.0,
        "RAW-MOCA": 438.0,
        "RAW-BOND": 3065.0,
        "RAW-CHEM": 225.0,
        "RAW-OXIDE": 59.0,
        "RAW-2020E": 2015.0,
    }

    raw_labels = {
        "ALM": "Aluminium (Insert)",
        "RAW-PU": "Polyurethane (PU)",
        "RAW-MOCA": "MOCA Curing Agent",
        "RAW-BOND": "Bonding Agent",
        "RAW-CHEM": "Chemical Additive",
        "RAW-OXIDE": "Aluminium Oxide",
        "RAW-2020E": "2020-E Stabilizer",
        "SCP": "Scrap",
    }

    raw_colors = {
        "ALM": "#0284c7",
        "RAW-PU": "#06b6d4",
        "RAW-MOCA": "#3b82f6",
        "RAW-BOND": "#6366f1",
        "RAW-CHEM": "#8b5cf6",
        "RAW-OXIDE": "#a855f7",
        "RAW-2020E": "#ec4899",
    }

    charge_colors = {
        "Labour Expense": "#f59e0b",
        "Electricity": "#eab308",
        "CNC Repairing and Tooling": "#10b981",
        "Admin Expense": "#64748b",
    }

    for item in inv_rows:
        stock = flt(item.stock)
        unit_price = flt(item.unit_price)
        total_amount = flt(item.total_amount) or (stock * unit_price)
        key = f"{item.product}_{item.stage}"

        if item.stage == "Raw" or not frappe.db.exists("BOM", item.product):
            pname = frappe.db.get_value("Product", item.product, "product_name") or item.product
            results[key] = {
                "product": item.product,
                "stage": item.stage,
                "stock": stock,
                "unit_price": unit_price,
                "total_amount": total_amount,
                "cost_heads": {
                    "material": {"name": "Raw Materials", "amount": total_amount, "unit_rate": unit_price, "percent": 100.0, "color": "#0284c7"},
                    "rejection": {"name": "Rejection Cost", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#ef4444"},
                    "labour": {"name": "Labour Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#f59e0b"},
                    "electricity": {"name": "Electricity", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#eab308"},
                    "cnc": {"name": "CNC Repair & Tooling", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#10b981"},
                    "admin": {"name": "Admin Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#64748b"},
                },
                "components": [
                    {
                        "name": raw_labels.get(item.product, pname),
                        "code": item.product,
                        "category": "Material",
                        "per_unit": unit_price,
                        "total": total_amount,
                        "percent": 100.0,
                        "color": raw_colors.get(item.product, "#0284c7"),
                    }
                ],
            }
            continue

        bom = frappe.get_doc("BOM", item.product)

        # Stage 1 material items
        s1_items = []
        s1_unit = 0.0
        for r in bom.stage1_items:
            rate = inventory_price(r.product, "Raw") or default_prices.get(r.product, 450.0)
            u = flt(r.per_unit_utilization) * rate
            s1_items.append({
                "name": raw_labels.get(r.product, r.product),
                "code": r.product,
                "category": "Material",
                "per_unit": u,
                "color": raw_colors.get(r.product, "#0284c7"),
            })
            s1_unit += u

        if item.stage == "Stage 1":
            scale = (unit_price / s1_unit) if (s1_unit and abs(unit_price - s1_unit) > 0.001) else 1.0
            comps = []
            for it in s1_items:
                pu = round(it["per_unit"] * scale, 2)
                tot = round(pu * stock, 2)
                pct = round((pu / unit_price * 100), 1) if unit_price else 0
                comps.append({**it, "per_unit": pu, "total": tot, "percent": pct})
            results[key] = {
                "product": item.product,
                "stage": item.stage,
                "stock": stock,
                "unit_price": unit_price,
                "total_amount": total_amount,
                "cost_heads": {
                    "material": {"name": "Raw Materials", "amount": total_amount, "unit_rate": unit_price, "percent": 100.0, "color": "#0284c7"},
                    "rejection": {"name": "Rejection Cost", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#ef4444"},
                    "labour": {"name": "Labour Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#f59e0b"},
                    "electricity": {"name": "Electricity", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#eab308"},
                    "cnc": {"name": "CNC Repair & Tooling", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#10b981"},
                    "admin": {"name": "Admin Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#64748b"},
                },
                "components": comps,
            }
            continue

        # Stage 2 materials
        s2_items = []
        s2_unit = 0.0
        for r in bom.stage2_items:
            rate = inventory_price(r.product, "Raw") or default_prices.get(r.product, 0)
            u = flt(r.per_unit_utilization) * rate
            s2_items.append({
                "name": raw_labels.get(r.product, r.product),
                "code": r.product,
                "category": "Material",
                "per_unit": u,
                "color": raw_colors.get(r.product, "#6366f1"),
            })
            s2_unit += u

        base_unit = s1_unit + s2_unit
        rejection_pct = 10.0
        latest_s2b = frappe.db.get_value("Stage 2 Batch", {"product": item.product, "is_completed": 1}, "rejection_percent")
        if latest_s2b is not None:
            rejection_pct = flt(latest_s2b)

        rejection_unit = base_unit * (rejection_pct / 100.0)
        s2_total_unit = base_unit + rejection_unit

        s3_charges = []
        s3_unit = 0.0
        for c in bom.stage3_charges:
            pu = flt(c.per_unit_price)
            s3_charges.append({
                "name": c.charge,
                "code": c.charge,
                "category": "Charge",
                "per_unit": pu,
                "color": charge_colors.get(c.charge, "#10b981"),
            })
            s3_unit += pu

        if item.stage == "Stage 2":
            full_unit = s2_total_unit
            scale = (unit_price / full_unit) if (full_unit and abs(unit_price - full_unit) > 0.001) else 1.0
            comps = []
            for it in [*s1_items, *s2_items]:
                pu = round(it["per_unit"] * scale, 2)
                comps.append({**it, "per_unit": pu, "total": round(pu * stock, 2), "percent": round((pu / unit_price * 100), 1) if unit_price else 0})
            rej_pu = round(rejection_unit * scale, 2)
            comps.append({
                "name": f"Rejection ({rejection_pct:.0f}%)",
                "code": "REJECTION",
                "category": "Rejection",
                "per_unit": rej_pu,
                "total": round(rej_pu * stock, 2),
                "percent": round((rej_pu / unit_price * 100), 1) if unit_price else 0,
                "color": "#ef4444",
            })
            mat_tot = sum(c["total"] for c in comps if c["category"] == "Material")
            rej_tot = sum(c["total"] for c in comps if c["category"] == "Rejection")
            results[key] = {
                "product": item.product,
                "stage": item.stage,
                "stock": stock,
                "unit_price": unit_price,
                "total_amount": total_amount,
                "cost_heads": {
                    "material": {"name": "Raw Materials", "amount": mat_tot, "unit_rate": round(mat_tot / stock, 2) if stock else 0, "percent": round(mat_tot / total_amount * 100, 1) if total_amount else 0, "color": "#0284c7"},
                    "rejection": {"name": "Rejection Cost", "amount": rej_tot, "unit_rate": round(rej_tot / stock, 2) if stock else 0, "percent": round(rej_tot / total_amount * 100, 1) if total_amount else 0, "color": "#ef4444"},
                    "labour": {"name": "Labour Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#f59e0b"},
                    "electricity": {"name": "Electricity", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#eab308"},
                    "cnc": {"name": "CNC Repair & Tooling", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#10b981"},
                    "admin": {"name": "Admin Expense", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#64748b"},
                },
                "components": comps,
            }
            continue

        # Finished Stage
        full_unit = s2_total_unit + s3_unit
        scale = (unit_price / full_unit) if (full_unit and abs(unit_price - full_unit) > 0.001) else 1.0

        comps = []
        for it in [*s1_items, *s2_items]:
            pu = round(it["per_unit"] * scale, 2)
            comps.append({**it, "per_unit": pu, "total": round(pu * stock, 2), "percent": round((pu / unit_price * 100), 1) if unit_price else 0})

        rej_pu = round(rejection_unit * scale, 2)
        comps.append({
            "name": f"Rejection ({rejection_pct:.0f}%)",
            "code": "REJECTION",
            "category": "Rejection",
            "per_unit": rej_pu,
            "total": round(rej_pu * stock, 2),
            "percent": round((rej_pu / unit_price * 100), 1) if unit_price else 0,
            "color": "#ef4444",
        })

        for it in s3_charges:
            pu = round(it["per_unit"] * scale, 2)
            comps.append({**it, "per_unit": pu, "total": round(pu * stock, 2), "percent": round((pu / unit_price * 100), 1) if unit_price else 0})

        mat_tot = sum(c["total"] for c in comps if c["category"] == "Material")
        rej_tot = sum(c["total"] for c in comps if c["category"] == "Rejection")
        lab_tot = sum(c["total"] for c in comps if "Labour" in c["name"])
        elec_tot = sum(c["total"] for c in comps if "Electricity" in c["name"])
        cnc_tot = sum(c["total"] for c in comps if "CNC" in c["name"])
        admin_tot = sum(c["total"] for c in comps if "Admin" in c["name"])

        results[key] = {
            "product": item.product,
            "stage": item.stage,
            "stock": stock,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "cost_heads": {
                "material": {"name": "Raw Materials", "amount": mat_tot, "unit_rate": round(mat_tot / stock, 2) if stock else 0, "percent": round(mat_tot / total_amount * 100, 1) if total_amount else 0, "color": "#0284c7"},
                "rejection": {"name": "Rejection Cost", "amount": rej_tot, "unit_rate": round(rej_tot / stock, 2) if stock else 0, "percent": round(rej_tot / total_amount * 100, 1) if total_amount else 0, "color": "#ef4444"},
                "labour": {"name": "Labour Expense", "amount": lab_tot, "unit_rate": round(lab_tot / stock, 2) if stock else 0, "percent": round(lab_tot / total_amount * 100, 1) if total_amount else 0, "color": "#f59e0b"},
                "electricity": {"name": "Electricity", "amount": elec_tot, "unit_rate": round(elec_tot / stock, 2) if stock else 0, "percent": round(elec_tot / total_amount * 100, 1) if total_amount else 0, "color": "#eab308"},
                "cnc": {"name": "CNC Repair & Tooling", "amount": cnc_tot, "unit_rate": round(cnc_tot / stock, 2) if stock else 0, "percent": round(cnc_tot / total_amount * 100, 1) if total_amount else 0, "color": "#10b981"},
                "admin": {"name": "Admin Expense", "amount": admin_tot, "unit_rate": round(admin_tot / stock, 2) if stock else 0, "percent": round(admin_tot / total_amount * 100, 1) if total_amount else 0, "color": "#64748b"},
            },
            "components": comps,
        }

    return results


@frappe.whitelist(methods=["POST"])
def run_action(doctype, name=None, action=None, args=None):
    """Execute a whitelisted action on a document.
    ``args`` is an optional dict for custom actions (e.g., items for create_dispatch_from_sales_order).
    The full return value of the action method is merged into the response so the frontend can
    access fields like ``name``, ``dispatch_status``, etc. directly on the result object.
    """
    if not action:
        frappe.throw(_("Action is required"), frappe.ValidationError)
    if action not in ACTIONS.get(doctype, set()):
        frappe.throw(_(f"Action {action} is not allowed on {doctype}."), frappe.PermissionError)

    # args may arrive as a JSON string when sent via form-encoded POST
    if isinstance(args, str):
        try:
            args = frappe.parse_json(args)
        except Exception:
            args = {}

    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    method = getattr(doc, action)
    result = method(**(args or {}))

    # If the action returned a dict (e.g. {name, dispatch_status}), merge it into the response
    # so the caller can do resp.name, resp.dispatch_status, etc.
    if isinstance(result, dict):
        return {**result, "doc_name": name}
    return {"name": name, "result": result}


@frappe.whitelist()
def test_tally_connection(tally_url="http://localhost:9000"):
    """Tests connectivity to Tally server and lists open companies."""
    from clssurya.utils.tally_sync import fetch_open_companies_from_tally, normalize_url
    url = normalize_url(tally_url)
    try:
        companies = fetch_open_companies_from_tally(url, timeout=7)
        return {
            "success": True,
            "url": url,
            "message": f"Connected to Tally! Found {len(companies)} open company(s)." if companies else "Connected to Tally server!",
            "companies": companies,
        }
    except Exception as e:
        msg = str(e)
        if "Connection refused" in msg or "Max retries exceeded" in msg:
            hint = f"Connection refused at {url}. Ensure Tally is running with ODBC / HTTP Server enabled in F12 > Advanced Configuration."
        elif "timed out" in msg:
            hint = f"Connection to {url} timed out. Verify network connectivity."
        else:
            hint = msg
        return {
            "success": False,
            "url": url,
            "message": f"Failed to connect to Tally: {hint}",
            "companies": [],
        }


@frappe.whitelist()
def fetch_tally_companies(tally_url="http://localhost:9000"):
    """Returns list of open companies in Tally."""
    from clssurya.utils.tally_sync import fetch_open_companies_from_tally
    try:
        companies = fetch_open_companies_from_tally(tally_url)
        return {"success": True, "companies": companies}
    except Exception as e:
        return {"success": False, "message": str(e), "companies": []}


@frappe.whitelist(methods=["POST"])
def sync_from_tally(tally_url="http://localhost:9000", company=None, group="Sundry Debtors"):
    """Fetches ledgers and bill ageing directly from Tally HTTP server and synchronizes into Frappe."""
    from clssurya.utils.tally_sync import (
        fetch_open_companies_from_tally,
        fetch_ledgers_from_tally,
        sync_customer_records,
    )
    url = tally_url.strip() if tally_url else "http://localhost:9000"

    if company and str(company).strip() and str(company).strip() != "__ALL__":
        target_companies = [str(company).strip()]
    else:
        try:
            target_companies = fetch_open_companies_from_tally(url)
        except Exception as e:
            frappe.throw(_("Could not fetch company list from Tally: {0}").format(str(e)))
        if not target_companies:
            target_companies = ["Main Company"]

    all_raw_customers = []
    errors = []

    for comp in target_companies:
        try:
            ledgers = fetch_ledgers_from_tally(url, company_name=comp, group_name=group or "Sundry Debtors")
            all_raw_customers.extend(ledgers)
        except Exception as e:
            errors.append(f"Company '{comp}': {str(e)}")

    if not all_raw_customers and errors:
        frappe.throw(_("Failed fetching from Tally: {0}").format("; ".join(errors)))

    sync_result = sync_customer_records(all_raw_customers, default_company=target_companies[0] if target_companies else None)
    if errors:
        sync_result["warnings"] = errors

    return sync_result


@frappe.whitelist(methods=["POST"])
def sync_customer_outstanding(customers=None, company=None):
    """Whitelisted endpoint accepting JSON customer payload to sync multi-company outstandings and ageing."""
    from clssurya.utils.tally_sync import sync_customer_records

    raw = customers
    if isinstance(raw, str):
        try:
            raw = frappe.parse_json(raw)
        except Exception:
            raw = []
    elif raw is None and frappe.request and frappe.request.data:
        try:
            data = frappe.parse_json(frappe.request.data.decode("utf-8"))
            raw = data.get("customers") or data
        except Exception:
            raw = []

    if isinstance(raw, dict):
        raw = [raw]

    return sync_customer_records(raw or [], default_company=company)


@frappe.whitelist()
def get_customer_outstandings_dashboard(company=None, search=None):
    """
    Returns complete dashboard data for Customer Outstanding:
    - Customer list with company-wise outstandings and ageing
    - Aggregated KPIs: Total Receivables (Dr), Total Payables (Cr), Net Outstanding
    - Company breakdown summary
    - Overall ageing summary
    """
    customers_raw = frappe.get_all(
        "Customer",
        fields=[
            "name", "customer_name", "gstin", "pan",
            "phone", "mobile", "email", "city", "state", "address",
            "total_outstanding", "balance_type", "active", "creation", "modified", "last_sync",
            "age_0_30", "age_30_60", "age_60_90", "age_90_120",
            "age_120_150", "age_150_180", "age_180_above"
        ],
        order_by="total_outstanding desc, customer_name asc"
    )

    outstandings_raw = frappe.db.sql(
        """SELECT name, parent, company_name, tally_company,
                  closing_balance, opening_balance, balance_type, last_sync,
                  age_0_30, age_30_60, age_60_90, age_90_120,
                  age_120_150, age_150_180, age_180_above
           FROM `tabCustomer Company Outstanding`
           WHERE parenttype = 'Customer'
           ORDER BY closing_balance DESC""",
        as_dict=True
    )

    comp_map = {}
    all_detected_companies = set()

    for row in outstandings_raw:
        p = str(row["parent"])
        if p not in comp_map:
            comp_map[p] = []
        c_name = row["company_name"]
        if c_name:
            all_detected_companies.add(c_name)

        comp_map[p].append({
            "name": row["name"],
            "company_name": c_name,
            "tally_company": row["tally_company"] or c_name,
            "closing_balance": flt(row["closing_balance"]),
            "opening_balance": flt(row["opening_balance"]),
            "balance_type": row["balance_type"] or "Dr",
            "last_sync": row["last_sync"],
            "age_0_30": flt(row.get("age_0_30", 0.0)),
            "age_30_60": flt(row.get("age_30_60", 0.0)),
            "age_60_90": flt(row.get("age_60_90", 0.0)),
            "age_90_120": flt(row.get("age_90_120", 0.0)),
            "age_120_150": flt(row.get("age_120_150", 0.0)),
            "age_150_180": flt(row.get("age_150_180", 0.0)),
            "age_180_above": flt(row.get("age_180_above", 0.0)),
        })

    try:
        registered_companies = frappe.get_all("Company", pluck="name")
        for rc in registered_companies:
            all_detected_companies.add(rc)
    except Exception:
        pass

    companies_stats = {
        c: {
            "receivables": 0.0,
            "payables": 0.0,
            "count": 0,
            "age_0_30": 0.0,
            "age_30_60": 0.0,
            "age_60_90": 0.0,
            "age_90_120": 0.0,
            "age_120_150": 0.0,
            "age_150_180": 0.0,
            "age_180_above": 0.0,
        }
        for c in all_detected_companies
    }

    selected_comp = company.strip() if company and company != "__ALL__" else None
    search_term = search.lower().strip() if search else None

    customer_list = []
    total_receivables = 0.0
    total_payables = 0.0
    gst_registered_count = 0

    total_age = {
        "age_0_30": 0.0,
        "age_30_60": 0.0,
        "age_60_90": 0.0,
        "age_90_120": 0.0,
        "age_120_150": 0.0,
        "age_150_180": 0.0,
        "age_180_above": 0.0,
    }

    for cust in customers_raw:
        c_id = str(cust["name"])
        rows = comp_map.get(c_id, [])

        if selected_comp:
            out_rows_to_use = [r for r in rows if r["company_name"] == selected_comp]
            if not out_rows_to_use:
                continue
        else:
            out_rows_to_use = rows

        if search_term:
            match_name = search_term in (cust.get("customer_name") or "").lower()
            match_gst = search_term in (cust.get("gstin") or "").lower()
            match_phone = search_term in (cust.get("phone") or "").lower() or search_term in (cust.get("mobile") or "").lower()
            match_city = search_term in (cust.get("city") or "").lower()
            if not (match_name or match_gst or match_phone or match_city):
                continue

        if cust.get("gstin"):
            gst_registered_count += 1

        cust_dr = 0.0
        cust_cr = 0.0
        c_age_0_30 = 0.0
        c_age_30_60 = 0.0
        c_age_60_90 = 0.0
        c_age_90_120 = 0.0
        c_age_120_150 = 0.0
        c_age_150_180 = 0.0
        c_age_180_above = 0.0

        for r in out_rows_to_use:
            c_name = r["company_name"]
            bal = flt(r["closing_balance"])
            if c_name not in companies_stats:
                companies_stats[c_name] = {
                    "receivables": 0.0,
                    "payables": 0.0,
                    "count": 0,
                    "age_0_30": 0.0,
                    "age_30_60": 0.0,
                    "age_60_90": 0.0,
                    "age_90_120": 0.0,
                    "age_120_150": 0.0,
                    "age_150_180": 0.0,
                    "age_180_above": 0.0,
                }
            companies_stats[c_name]["count"] += 1

            r_a0 = flt(r["age_0_30"])
            r_a30 = flt(r["age_30_60"])
            r_a60 = flt(r["age_60_90"])
            r_a90 = flt(r["age_90_120"])
            r_a120 = flt(r["age_120_150"])
            r_a150 = flt(r["age_150_180"])
            r_a180 = flt(r["age_180_above"])

            c_age_0_30 += r_a0
            c_age_30_60 += r_a30
            c_age_60_90 += r_a60
            c_age_90_120 += r_a90
            c_age_120_150 += r_a120
            c_age_150_180 += r_a150
            c_age_180_above += r_a180

            companies_stats[c_name]["age_0_30"] += r_a0
            companies_stats[c_name]["age_30_60"] += r_a30
            companies_stats[c_name]["age_60_90"] += r_a60
            companies_stats[c_name]["age_90_120"] += r_a90
            companies_stats[c_name]["age_120_150"] += r_a120
            companies_stats[c_name]["age_150_180"] += r_a150
            companies_stats[c_name]["age_180_above"] += r_a180

            total_age["age_0_30"] += r_a0
            total_age["age_30_60"] += r_a30
            total_age["age_60_90"] += r_a60
            total_age["age_90_120"] += r_a90
            total_age["age_120_150"] += r_a120
            total_age["age_150_180"] += r_a150
            total_age["age_180_above"] += r_a180

            if r["balance_type"] == "Cr":
                cust_cr += bal
                total_payables += bal
                companies_stats[c_name]["payables"] += bal
            else:
                cust_dr += bal
                total_receivables += bal
                companies_stats[c_name]["receivables"] += bal

        if not rows:
            bal = flt(cust["total_outstanding"])
            if cust["balance_type"] == "Cr":
                cust_cr = bal
                total_payables += bal
            else:
                cust_dr = bal
                total_receivables += bal
            c_age_0_30 = flt(cust.get("age_0_30", 0.0))
            c_age_30_60 = flt(cust.get("age_30_60", 0.0))
            c_age_60_90 = flt(cust.get("age_60_90", 0.0))
            c_age_90_120 = flt(cust.get("age_90_120", 0.0))
            c_age_120_150 = flt(cust.get("age_120_150", 0.0))
            c_age_150_180 = flt(cust.get("age_150_180", 0.0))
            c_age_180_above = flt(cust.get("age_180_above", 0.0))

            total_age["age_0_30"] += c_age_0_30
            total_age["age_30_60"] += c_age_30_60
            total_age["age_60_90"] += c_age_60_90
            total_age["age_90_120"] += c_age_90_120
            total_age["age_120_150"] += c_age_120_150
            total_age["age_150_180"] += c_age_150_180
            total_age["age_180_above"] += c_age_180_above

        customer_list.append({
            **cust,
            "company_outstandings": out_rows_to_use,
            "receivable_dr": round(cust_dr, 2),
            "payable_cr": round(cust_cr, 2),
            "net_balance": round(cust_dr - cust_cr, 2),
            "age_0_30": round(c_age_0_30, 2),
            "age_30_60": round(c_age_30_60, 2),
            "age_60_90": round(c_age_60_90, 2),
            "age_90_120": round(c_age_90_120, 2),
            "age_120_150": round(c_age_120_150, 2),
            "age_150_180": round(c_age_150_180, 2),
            "age_180_above": round(c_age_180_above, 2),
        })

    companies_breakdown = []
    for comp_name, stats in companies_stats.items():
        companies_breakdown.append({
            "company_name": comp_name,
            "customer_count": stats["count"],
            "receivables": round(stats["receivables"], 2),
            "payables": round(stats["payables"], 2),
            "net_amount": round(stats["receivables"] - stats["payables"], 2),
            "age_0_30": round(stats["age_0_30"], 2),
            "age_30_60": round(stats["age_30_60"], 2),
            "age_60_90": round(stats["age_60_90"], 2),
            "age_90_120": round(stats["age_90_120"], 2),
            "age_120_150": round(stats["age_120_150"], 2),
            "age_150_180": round(stats["age_150_180"], 2),
            "age_180_above": round(stats["age_180_above"], 2),
        })

    companies_breakdown.sort(key=lambda x: x["receivables"], reverse=True)

    return {
        "customers": customer_list,
        "total_customers": len(customer_list),
        "total_receivables": round(total_receivables, 2),
        "total_payables": round(total_payables, 2),
        "net_outstanding": round(total_receivables - total_payables, 2),
        "gst_registered_count": gst_registered_count,
        "companies": sorted(list(all_detected_companies)),
        "companies_breakdown": companies_breakdown,
        "ageing_summary": {
            "age_0_30": round(total_age["age_0_30"], 2),
            "age_30_60": round(total_age["age_30_60"], 2),
            "age_60_90": round(total_age["age_60_90"], 2),
            "age_90_120": round(total_age["age_90_120"], 2),
            "age_120_150": round(total_age["age_120_150"], 2),
            "age_150_180": round(total_age["age_150_180"], 2),
            "age_180_above": round(total_age["age_180_above"], 2),
            "total": round(sum(total_age.values()), 2),
        },
    }


@frappe.whitelist()
def get_dispatch_return_items(dispatch_name):
    """
    Return a list of dispatch items with their returnable quantities for the Return dialog.
    Called by the frontend before opening the ReturnDialog.
    """
    if not frappe.has_permission("Dispatch", "read"):
        raise frappe.PermissionError

    disp = frappe.get_doc("Dispatch", dispatch_name)

    if disp.dispatch_status != "Dispatched":
        frappe.throw(
            _("Returns can only be created against a confirmed (Dispatched) dispatch. "
              "Dispatch {0} is currently '{1}'.").format(dispatch_name, disp.dispatch_status)
        )

    # Collect all confirmed returned qtys per dispatch item row
    confirmed_returns = frappe.get_all(
        "Customer Return",
        filters={"dispatch": dispatch_name, "return_status": "Confirmed"},
        pluck="name",
    )
    already_returned = {}  # dispatch_item_name → total confirmed returned qty
    for rname in confirmed_returns:
        rdoc = frappe.get_doc("Customer Return", rname)
        for row in rdoc.items:
            already_returned[row.dispatch_item] = already_returned.get(row.dispatch_item, 0.0) + flt(row.return_qty)

    items = []
    for di in disp.items:
        dispatched = flt(di.quantity)
        returned = already_returned.get(di.name, 0.0)
        returnable = max(0.0, dispatched - returned)
        items.append({
            "dispatch_item": di.name,
            "order_item": di.order_item,
            "product": di.product,
            "product_name": frappe.db.get_value("Product", di.product, "product_name") or di.product,
            "dispatched_qty": dispatched,
            "already_returned": returned,
            "returnable_qty": returnable,
            "unit_cost": flt(di.unit_cost),
        })

    return {
        "dispatch_name": dispatch_name,
        "sales_order": disp.sales_order,
        "customer": disp.customer,
        "items": items,
    }


@frappe.whitelist()
def get_dispatch_returns(dispatch_name):
    """Return all Customer Return records linked to a dispatch for display in the UI."""
    if not frappe.has_permission("Customer Return", "read"):
        raise frappe.PermissionError

    returns = frappe.get_all(
        "Customer Return",
        filters={"dispatch": dispatch_name},
        fields=["name", "return_date", "return_status", "return_reason", "confirmed_on", "confirmed_by"],
        order_by="creation desc",
    )
    result = []
    for r in returns:
        doc = frappe.get_doc("Customer Return", r.name)
        r["items"] = [
            {
                "product": row.product,
                "product_name": frappe.db.get_value("Product", row.product, "product_name") or row.product,
                "return_qty": flt(row.return_qty),
                "condition": row.condition,
                "dispatched_qty": flt(row.dispatched_qty),
            }
            for row in doc.items
        ]
        result.append(r)
    return result


@frappe.whitelist()
def get_purchase_order_receipt_items(purchase_order):
    """Return pending items and metadata for Goods Receipt creation."""
    if not frappe.has_permission("Purchase Entry", "read"):
        raise frappe.PermissionError
    po = frappe.get_doc("Purchase Entry", purchase_order)
    return po.get_pending_items()


@frappe.whitelist()
def get_purchase_order_receipts(purchase_order):
    """Return all Goods Receipt records linked to a Purchase Order."""
    if not frappe.has_permission("Goods Receipt", "read"):
        raise frappe.PermissionError

    receipts = frappe.get_all(
        "Goods Receipt",
        filters={"purchase_order": purchase_order},
        fields=["name", "posting_date", "status", "supplier_delivery_note", "remarks", "total_qty", "total_amount", "confirmed_on", "confirmed_by"],
        order_by="creation desc",
    )
    result = []
    for r in receipts:
        doc = frappe.get_doc("Goods Receipt", r.name)
        r["items"] = [
            {
                "product": row.product,
                "product_name": row.product_name or frappe.db.get_value("Product", row.product, "product_name") or row.product,
                "uom": row.uom,
                "ordered_qty": flt(row.ordered_qty),
                "already_received_qty": flt(row.already_received_qty),
                "pending_qty": flt(row.pending_qty),
                "received_qty": flt(row.received_qty),
                "rate": flt(row.rate),
                "landed_rate": flt(row.landed_rate),
                "amount": flt(row.amount),
            }
            for row in doc.items
        ]
        result.append(r)
    return result


@frappe.whitelist()
def create_and_confirm_goods_receipt(purchase_order, posting_date=None, supplier_delivery_note=None, remarks=None, items=None):
    """Create and confirm a Goods Receipt in one transaction."""
    from frappe.utils import nowdate
    if not frappe.has_permission("Goods Receipt", "create"):
        raise frappe.PermissionError

    if isinstance(items, str):
        items = frappe.parse_json(items)

    gr = frappe.new_doc("Goods Receipt")
    gr.purchase_order = purchase_order
    gr.posting_date = posting_date or nowdate()
    gr.supplier_delivery_note = supplier_delivery_note or ""
    gr.remarks = remarks or ""
    for it in items or []:
        if flt(it.get("received_qty")) > 0:
            gr.append("items", {
                "purchase_order_item": it.get("purchase_order_item"),
                "product": it.get("product"),
                "received_qty": flt(it.get("received_qty")),
            })
    gr.insert(ignore_permissions=False)
    confirm_res = gr.confirm_receipt()
    return {"name": gr.name, "status": gr.status, **confirm_res}


@frappe.whitelist()
def cancel_goods_receipt(goods_receipt_name):
    """Cancel a Goods Receipt and reverse stock."""
    gr = frappe.get_doc("Goods Receipt", goods_receipt_name)
    return gr.cancel_receipt()


# =============================================================================
# MASTER IMPLEMENTATION: UNIFIED INVENTORY & PRODUCTION REPORTS
# =============================================================================

STAGE_DISPLAY_MAP = {
    "Raw": "Raw Material",
    "Stage 1": "Stage 1 (Insert Making)",
    "Stage 2": "Stage 2 (PU & Casting)",
    "Stage 3": "Stage 3 (CNC)",
    "Finished": "Finished Goods",
}

STAGE_INTERNAL_MAP = {
    "Raw Material": "Raw",
    "Raw": "Raw",
    "Insert": "Stage 1",
    "Stage 1": "Stage 1",
    "Casting": "Stage 2",
    "Stage 2": "Stage 2",
    "CNC / Charge": "Stage 3",
    "CNC": "Stage 3",
    "Stage 3": "Stage 3",
    "Finished Goods": "Finished",
    "Finished": "Finished",
}

@frappe.whitelist()
def get_inventory_ledger(from_date=None, to_date=None, product=None, stage=None, transaction_type=None, batch_no=None, page=1, page_size=100):
    """
    Section 2: Authoritative Stock Ledger & Historical Inventory Report.
    Calculates correct historical opening balance before `from_date` and closing balance through `to_date`.
    """
    if not (frappe.has_permission("Inventory", "read") or frappe.has_permission("Stock Ledger Entry", "read")):
        raise frappe.PermissionError

    from frappe.utils import getdate, nowdate, add_days

    # Defaults
    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -30)

    from_dt_str = f"{from_date} 00:00:00"
    to_dt_str = f"{to_date} 23:59:59"

    # Stage filter normalization
    internal_stage = STAGE_INTERNAL_MAP.get(stage, stage) if stage and stage != "All" else None

    # Base query conditions
    conds = []
    params = {}

    if product:
        # Search by product name or code
        matching_products = frappe.db.sql(
            "SELECT name FROM `tabProduct` WHERE name LIKE %(p)s OR product_name LIKE %(p)s OR product_code LIKE %(p)s",
            {"p": f"%{product}%"},
            pluck="name"
        )
        if matching_products:
            conds.append("product IN %(products)s")
            params["products"] = tuple(matching_products)
        else:
            conds.append("product = %(product)s")
            params["product"] = product

    if internal_stage:
        conds.append("stage = %(stage)s")
        params["stage"] = internal_stage

    if transaction_type and transaction_type != "All":
        conds.append("reference_doctype = %(tx_type)s")
        params["tx_type"] = transaction_type

    if batch_no:
        conds.append("reference_name LIKE %(batch_no)s")
        params["batch_no"] = f"%{batch_no}%"

    extra_sql = (" AND " + " AND ".join(conds)) if conds else ""

    # 1. Calculate historical opening balances strictly before from_date
    open_params = dict(params)
    open_params["from_dt"] = from_dt_str
    open_sql = f"""
        SELECT 
            product,
            stage,
            COALESCE(SUM(qty_in - qty_out), 0) AS opening_qty
        FROM `tabStock Ledger Entry`
        WHERE posting_datetime < %(from_dt)s
        {extra_sql}
        GROUP BY product, stage
    """
    open_rows = frappe.db.sql(open_sql, open_params, as_dict=True)
    opening_by_ps = {(r.product, r.stage): flt(r.opening_qty) for r in open_rows}

    # 2. Query transactions within the selected date range
    range_params = dict(params)
    range_params["from_dt"] = from_dt_str
    range_params["to_dt"] = to_dt_str
    range_sql = f"""
        SELECT 
            name,
            posting_datetime,
            product,
            stage,
            reference_doctype,
            reference_name,
            qty_in,
            qty_out,
            unit_price,
            value,
            is_reversal,
            is_reversed,
            creation
        FROM `tabStock Ledger Entry`
        WHERE posting_datetime >= %(from_dt)s AND posting_datetime <= %(to_dt)s
        {extra_sql}
        ORDER BY posting_datetime ASC, creation ASC, name ASC
    """
    entries = frappe.db.sql(range_sql, range_params, as_dict=True)

    # Cache product info
    prod_codes = list(set([e.product for e in entries] + [r.product for r in open_rows]))
    prod_map = {}
    if prod_codes:
        prods = frappe.db.sql(
            "SELECT name, product_code, product_name, uom, category FROM `tabProduct` WHERE name IN %(names)s",
            {"names": tuple(prod_codes)},
            as_dict=True
        )
        prod_map = {p.name: p for p in prods}

    # Calculate running balance for each movement
    running_balances = dict(opening_by_ps)
    ledger_rows = []

    total_in = 0.0
    total_out = 0.0

    for e in entries:
        key = (e.product, e.stage)
        open_bal = running_balances.get(key, 0.0)
        q_in = flt(e.qty_in)
        q_out = flt(e.qty_out)
        close_bal = open_bal + q_in - q_out
        running_balances[key] = close_bal

        total_in += q_in
        total_out += q_out

        p_info = prod_map.get(e.product, {})
        display_stage = STAGE_DISPLAY_MAP.get(e.stage, e.stage)

        ledger_rows.append({
            "name": e.name,
            "transaction_date": str(e.posting_datetime)[:19] if e.posting_datetime else "",
            "product_code": p_info.get("product_code") or e.product,
            "product_name": p_info.get("product_name") or e.product,
            "stage": e.stage,
            "stage_label": display_stage,
            "transaction_type": e.reference_doctype or "",
            "reference_name": e.reference_name or "",
            "opening_qty": round(open_bal, 3),
            "stock_in": round(q_in, 3),
            "stock_out": round(q_out, 3),
            "closing_qty": round(close_bal, 3),
            "uom": p_info.get("uom") or "",
            "unit_price": flt(e.unit_price),
            "value": flt(e.value),
            "is_reversal": cint(e.is_reversal),
            "is_reversed": cint(e.is_reversed),
        })

    # Total historical opening and closing
    total_opening = sum(opening_by_ps.values())
    total_closing = total_opening + total_in - total_out

    # Per-stage opening/closing summary
    stage_summaries = {}
    all_stages = ["Raw", "Stage 1", "Stage 2", "Stage 3", "Finished"]
    for stg in all_stages:
        stg_open = sum(v for k, v in opening_by_ps.items() if k[1] == stg)
        stg_in = sum(e["stock_in"] for e in ledger_rows if e["stage"] == stg)
        stg_out = sum(e["stock_out"] for e in ledger_rows if e["stage"] == stg)
        stg_close = stg_open + stg_in - stg_out
        stage_summaries[STAGE_DISPLAY_MAP.get(stg, stg)] = {
            "internal_stage": stg,
            "display_label": STAGE_DISPLAY_MAP.get(stg, stg),
            "opening": round(stg_open, 2),
            "in": round(stg_in, 2),
            "out": round(stg_out, 2),
            "closing": round(stg_close, 2),
        }

    return {
        "from_date": from_date,
        "to_date": to_date,
        "ledger": ledger_rows,
        "total_count": len(ledger_rows),
        "summary": {
            "total_opening": round(total_opening, 2),
            "total_in": round(total_in, 2),
            "total_out": round(total_out, 2),
            "total_closing": round(total_closing, 2),
        },
        "stage_summaries": stage_summaries,
    }


@frappe.whitelist()
def get_production_report(from_date=None, to_date=None, product=None, stage=None, process=None, operator=None, batch_no=None):
    """
    Section 3: Dedicated Production Report API.
    Retrieves real production transactions across Stage 1 (Insert), Stage 2 (Casting), Stage 3 (CNC / Charge).
    Correctly aggregates finished production using the final configured stage per product without double-counting.
    """
    from frappe.utils import getdate, nowdate, add_days

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -30)

    stage_configs = [
        {"doctype": "Stage 1 Batch", "stage": "Stage 1", "label": "Insert", "step": 1},
        {"doctype": "Stage 2 Batch", "stage": "Stage 2", "label": "Casting", "step": 2},
        {"doctype": "Stage 3 Batch", "stage": "Stage 3", "label": "CNC / Charge", "step": 3},
    ]

    # Filter stages if requested
    if stage and stage != "All":
        target = STAGE_INTERNAL_MAP.get(stage, stage)
        stage_configs = [s for s in stage_configs if s["stage"] == target or s["label"] == stage]

    all_batches = []
    prod_cache = {}

    for cfg in stage_configs:
        dt = cfg["doctype"]
        conds = ["posting_date >= %(from_date)s AND posting_date <= %(to_date)s"]
        params = {"from_date": from_date, "to_date": to_date}

        if product:
            conds.append("product LIKE %(product)s")
            params["product"] = f"%{product}%"
        if batch_no:
            conds.append("name LIKE %(batch_no)s")
            params["batch_no"] = f"%{batch_no}%"
        if operator:
            conds.append("operator LIKE %(operator)s")
            params["operator"] = f"%{operator}%"
        if process:
            conds.append("process LIKE %(process)s")
            params["process"] = f"%{process}%"

        where_clause = " WHERE " + " AND ".join(conds)
        sql = f"""
            SELECT 
                name,
                posting_date,
                product,
                quantity,
                rejection_percent,
                rejection_amount,
                unit_cost,
                batch_total,
                is_completed,
                completed_on,
                completed_by,
                status,
                operator,
                process,
                machine,
                input_qty,
                accepted_qty,
                rejected_qty,
                remaining_qty
            FROM `tab{dt}`
            {where_clause}
            ORDER BY posting_date DESC, creation DESC
        """
        rows = frappe.db.sql(sql, params, as_dict=True)

        for r in rows:
            p_name = r.product
            if p_name not in prod_cache:
                p_doc = frappe.db.get_value("Product", p_name, ["product_code", "product_name", "uom", "total_steps"], as_dict=True)
                prod_cache[p_name] = p_doc or {}
            p_info = prod_cache[p_name]

            total_steps = cint(p_info.get("total_steps") or 3)
            is_final_stage = (cfg["step"] == total_steps)

            qty = flt(r.quantity)
            rej_qty = flt(r.rejected_qty) if r.rejected_qty is not None else (qty * flt(r.rejection_percent) / 100.0)
            in_qty = flt(r.input_qty) or qty
            rem_qty = flt(r.remaining_qty) if r.remaining_qty is not None else max(0.0, in_qty - qty - rej_qty)

            status_val = r.status or ("Completed" if cint(r.is_completed) else "Draft")

            all_batches.append({
                "batch_number": r.name,
                "production_date": str(r.posting_date) if r.posting_date else "",
                "product_code": p_info.get("product_code") or r.product,
                "product_name": p_info.get("product_name") or r.product,
                "production_stage": cfg["stage"],
                "production_stage_label": cfg["label"],
                "stage_step": cfg["step"],
                "total_steps": total_steps,
                "is_final_stage": is_final_stage,
                "process_name": r.process or "",
                "operator": r.operator or (r.completed_by or ""),
                "machine": r.machine or "",
                "input_qty": round(in_qty, 3),
                "accepted_output_qty": round(qty, 3),
                "rejected_qty": round(rej_qty, 3),
                "remaining_qty": round(rem_qty, 3),
                "uom": p_info.get("uom") or "",
                "unit_cost": flt(r.unit_cost),
                "batch_total": flt(r.batch_total),
                "transaction_status": status_val,
                "is_completed": cint(r.is_completed),
            })

    # Sort chronologically or by date desc
    all_batches.sort(key=lambda x: (x["production_date"], x["batch_number"]), reverse=True)

    # Section 3.3 Rule 7-9: Calculate finished production without double-counting!
    # Finished production is only accepted output from the final configured stage of each product
    active_batches = [b for b in all_batches if b["transaction_status"] != "Cancelled"]

    total_insert_output = sum(b["accepted_output_qty"] for b in active_batches if b["production_stage"] == "Stage 1")
    total_casting_output = sum(b["accepted_output_qty"] for b in active_batches if b["production_stage"] == "Stage 2")
    total_cnc_output = sum(b["accepted_output_qty"] for b in active_batches if b["production_stage"] == "Stage 3")

    total_finished_production = sum(b["accepted_output_qty"] for b in active_batches if b["is_final_stage"])
    total_rejected = sum(b["rejected_qty"] for b in active_batches)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "batches": all_batches,
        "total_count": len(all_batches),
        "summary": {
            "total_finished_production": round(total_finished_production, 2),
            "insert_output": round(total_insert_output, 2),
            "casting_output": round(total_casting_output, 2),
            "cnc_output": round(total_cnc_output, 2),
            "total_rejected": round(total_rejected, 2),
            "active_batch_count": len(active_batches),
        }
    }


@frappe.whitelist()
def get_monthly_production_report(
    from_date=None,
    to_date=None,
    month_year=None,
    product=None,
    product_code=None,
    production_code=None,
    category=None,
    stage=None,
    operator=None,
    batch_no=None,
):
    """
    Monthly Product-wise Production Report with Stage-wise Totals.
    Aggregates Stage 1, Stage 2, Stage 3, Finished Goods, Rejected Qty,
    and Net Total Production Cost according to product and selected date range.
    """
    import datetime
    from frappe.utils import getdate, nowdate, add_months

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = str(add_months(getdate(to_date), -1))[:10]

    from_str = str(from_date)[:10] if from_date else ""
    to_str = str(to_date)[:10] if to_date else ""

    # 1. Product Cache
    product_cache = {}
    def get_prod(p_id):
        if not p_id:
            return {}
        if p_id not in product_cache:
            try:
                doc = frappe.get_doc("Product", p_id)
                product_cache[p_id] = {
                    "product_name": doc.get("product_name") or p_id,
                    "product_code": doc.get("product_code") or p_id,
                    "production_code": doc.get("production_code") or "",
                    "uom": doc.get("uom") or "PCS",
                }
            except Exception:
                product_cache[p_id] = {
                    "product_name": p_id,
                    "product_code": p_id,
                    "production_code": "",
                    "uom": "PCS",
                }
        return product_cache[p_id]

    # 2. Stage Batches Query
    stage_batches = []
    for stg_num, stg_label in [(1, "Stage 1 – Insert Making"), (2, "Stage 2 – PU & Casting"), (3, "Stage 3 – CNC")]:
        dt = f"Stage {stg_num} Batch"
        filters = {"docstatus": ["!=", 2]}
        if from_str and to_str:
            filters["posting_date"] = ["between", [from_str, to_str]]
        elif from_str:
            filters["posting_date"] = [">=", from_str]
        elif to_str:
            filters["posting_date"] = ["<=", to_str]

        try:
            rows = frappe.get_all(
                dt,
                filters=filters,
                fields=[
                    "name", "product", "quantity", "posting_date", "status",
                    "is_completed", "added_cost", "carried_cost", "batch_total",
                    "unit_cost", "rejection_percent", "rejection_amount",
                    "production_code", "remarks"
                ],
                order_by="posting_date asc",
                ignore_permissions=True,
            )
            for r in rows:
                if r.get("status") == "Cancelled":
                    continue
                r["stage_num"] = stg_num
                r["stage_label"] = stg_label
                stage_batches.append(r)
        except Exception as exc:
            frappe.log_error(str(exc), f"get_monthly_production_report: {dt}")

    # 3. Finished Goods in Inventory
    fg_by_product = {}
    try:
        fg_rows = frappe.get_all(
            "Inventory",
            filters={"stage": "Finished"},
            fields=["name", "product", "stock", "unit_price", "creation", "modified"],
            ignore_permissions=True,
        )
        for fg in fg_rows:
            p_val = fg.get("product") or ""
            stock = float(fg.get("stock") or 0)
            fg_by_product[p_val] = fg_by_product.get(p_val, 0.0) + stock
    except Exception as exc:
        frappe.log_error(str(exc), "get_monthly_production_report: FG query")

    # 4. Group Batches by Product
    groups = {}
    for b in stage_batches:
        p_id = b.get("product") or ""
        p_info = get_prod(p_id)
        p_code = p_info.get("product_code") or p_id
        prod_name = p_info.get("product_name") or p_id
        uom = p_info.get("uom") or "PCS"
        prod_c = b.get("production_code") or p_info.get("production_code") or ""

        # Filter by product or code if requested
        if product and (product.lower() not in p_id.lower() and product.lower() not in prod_name.lower()):
            continue
        if product_code and (product_code.lower() not in p_code.lower()):
            continue
        if production_code and (production_code.lower() not in prod_c.lower()):
            continue

        raw_date = str(b.get("posting_date") or "")[:10]
        m_num = 1
        m_year = 2026
        month_name = "October 2026"
        if raw_date:
            try:
                d_obj = datetime.datetime.strptime(raw_date, "%Y-%m-%d")
                m_num = d_obj.month
                m_year = d_obj.year
                month_name = d_obj.strftime("%B %Y")
            except Exception:
                pass

        group_key = p_id

        if group_key not in groups:
            groups[group_key] = {
                "month_no": m_num,
                "month": month_name,
                "year": m_year,
                "production_date": raw_date,
                "product": p_id,
                "product_code": p_code,
                "production_code": prod_c or "—",
                "product_name": prod_name,
                "uom": uom,
                "stage1_qty": 0.0,
                "stage2_qty": 0.0,
                "stage3_qty": 0.0,
                "finished_goods_qty": 0.0,
                "rejected_qty": 0.0,
                "total_production_cost": 0.0,
                "batch_count": 0,
                "insert_input": 0.0,
                "insert_output": 0.0,
                "casting_input": 0.0,
                "casting_output": 0.0,
                "cnc_input": 0.0,
                "cnc_output": 0.0,
                "total_accepted_final": 0.0,
                "batches": [],
            }

        g = groups[group_key]
        if raw_date and raw_date > g["production_date"]:
            g["production_date"] = raw_date
        if prod_c and (not g["production_code"] or g["production_code"] == "—"):
            g["production_code"] = prod_c

        qty = float(b.get("quantity") or 0)
        rej_pct = float(b.get("rejection_percent") or 0)
        rej_amt = float(b.get("rejected_qty") or 0)
        if rej_amt <= 0 and rej_pct > 0:
            rej_amt = round(qty * rej_pct / 100, 4)

        b_total = float(b.get("batch_total") or 0)
        carried = float(b.get("carried_cost") or 0)
        added = float(b.get("added_cost") or 0)

        # Net production cost newly incurred by this batch
        if b["stage_num"] == 1:
            net_cost = b_total if b_total > 0 else added
            g["stage1_qty"] += qty
            g["insert_input"] += qty
            g["insert_output"] += (qty - rej_amt)
        elif b["stage_num"] == 2:
            if carried > 0 and b_total >= carried:
                net_cost = b_total - carried
            else:
                net_cost = added if added > 0 else b_total
            g["stage2_qty"] += qty
            g["casting_input"] += qty
            g["casting_output"] += (qty - rej_amt)
        else:
            if carried > 0 and b_total >= carried:
                net_cost = b_total - carried
            else:
                net_cost = added if added > 0 else b_total
            g["stage3_qty"] += qty
            g["cnc_input"] += qty
            g["cnc_output"] += (qty - rej_amt)

        g["rejected_qty"] += rej_amt
        g["total_production_cost"] += net_cost
        g["batch_count"] += 1

        g["batches"].append({
            "production_date": raw_date,
            "batch_no": b.get("name") or "",
            "product_code": p_code,
            "production_code": prod_c,
            "product_name": prod_name,
            "stage": b.get("stage_label") or f"Stage {b['stage_num']}",
            "produced_qty": qty,
            "rejected_qty": rej_amt,
            "batch_status": b.get("status") or "Completed",
            "production_cost": b_total,
            "unit_cost": float(b.get("unit_cost") or 0),
        })

    # 5. Populate Finished Goods
    for p_id, g in groups.items():
        fg_qty = fg_by_product.get(p_id, 0.0) or fg_by_product.get(g["product_code"], 0.0)
        if fg_qty > 0:
            g["finished_goods_qty"] = fg_qty
        elif g["stage3_qty"] > 0:
            g["finished_goods_qty"] = max(0.0, g["stage3_qty"] - g["rejected_qty"])

        g["total_accepted_final"] = g["finished_goods_qty"]
        g["stage1_qty"] = round(g["stage1_qty"], 2)
        g["stage2_qty"] = round(g["stage2_qty"], 2)
        g["stage3_qty"] = round(g["stage3_qty"], 2)
        g["finished_goods_qty"] = round(g["finished_goods_qty"], 2)
        g["rejected_qty"] = round(g["rejected_qty"], 2)
        g["total_production_cost"] = round(g["total_production_cost"], 2)

    rows = list(groups.values())
    rows.sort(key=lambda x: (x["production_date"], x["product_name"]), reverse=True)

    return {
        "from_date": from_str,
        "to_date": to_str,
        "rows": rows,
        "total_count": len(rows),
    }


@frappe.whitelist()
def get_cnc_machine_report(from_date=None, to_date=None, machine=None, product=None, operator=None, process=None):
    """
    Section 7: CNC Machine-wise Production and Time Tracking Report.
    """
    from frappe.utils import nowdate, add_days

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -30)

    conds = ["production_date >= %(from_date)s AND production_date <= %(to_date)s"]
    params = {"from_date": from_date, "to_date": to_date}

    if machine and machine != "All":
        conds.append("machine = %(machine)s")
        params["machine"] = machine
    if product:
        conds.append("product LIKE %(product)s")
        params["product"] = f"%{product}%"
    if operator:
        conds.append("operator LIKE %(operator)s")
        params["operator"] = f"%{operator}%"
    if process:
        conds.append("process LIKE %(process)s")
        params["process"] = f"%{process}%"

    where_sql = " WHERE " + " AND ".join(conds)
    logs = frappe.db.sql(f"""
        SELECT 
            name,
            machine,
            production_date,
            production_batch,
            product,
            product_name,
            process,
            operator,
            start_time,
            end_time,
            total_duration_mins,
            running_time_mins,
            downtime_mins,
            qty_processed,
            accepted_qty,
            rejected_qty,
            remarks
        FROM `tabCNC Machine Log`
        {where_sql}
        ORDER BY production_date DESC, start_time DESC
    """, params, as_dict=True)

    # Machine summary aggregation
    machine_summary = {}
    for l in logs:
        m = l.machine
        if m not in machine_summary:
            m_doc = frappe.db.get_value("CNC Machine", m, ["machine_name", "machine_type"], as_dict=True)
            machine_summary[m] = {
                "machine": m,
                "machine_name": m_doc.machine_name if m_doc else m,
                "machine_type": m_doc.machine_type if m_doc else "",
                "total_duration_hours": 0.0,
                "total_running_hours": 0.0,
                "total_downtime_hours": 0.0,
                "total_processed": 0.0,
                "total_accepted": 0.0,
                "total_rejected": 0.0,
                "log_count": 0,
            }
        s = machine_summary[m]
        s["total_duration_hours"] += flt(l.total_duration_mins) / 60.0
        s["total_running_hours"] += flt(l.running_time_mins) / 60.0
        s["total_downtime_hours"] += flt(l.downtime_mins) / 60.0
        s["total_processed"] += flt(l.qty_processed)
        s["total_accepted"] += flt(l.accepted_qty)
        s["total_rejected"] += flt(l.rejected_qty)
        s["log_count"] += 1

    summary_rows = list(machine_summary.values())
    for s in summary_rows:
        s["total_duration_hours"] = round(s["total_duration_hours"], 2)
        s["total_running_hours"] = round(s["total_running_hours"], 2)
        s["total_downtime_hours"] = round(s["total_downtime_hours"], 2)
        acc = s["total_accepted"]
        tot_dur_mins = s["total_duration_hours"] * 60.0
        s["avg_mins_per_unit"] = round(tot_dur_mins / acc, 2) if acc > 0 else 0.0
        s["rejection_percent"] = round((s["total_rejected"] / s["total_processed"] * 100.0), 2) if s["total_processed"] > 0 else 0.0

    return {
        "from_date": from_date,
        "to_date": to_date,
        "logs": logs,
        "machine_summary": summary_rows,
        "total_count": len(logs),
    }


@frappe.whitelist()
def get_purchase_shortage_report(from_date=None, to_date=None, supplier=None, product=None, purchase_order=None, claim_status=None):
    """
    Section 11: Purchase Shortage and Credit Note Report.
    """
    from frappe.utils import nowdate, add_days

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -60)

    conds = ["report_date >= %(from_date)s AND report_date <= %(to_date)s"]
    params = {"from_date": from_date, "to_date": to_date}

    if supplier and supplier != "All":
        conds.append("supplier = %(supplier)s")
        params["supplier"] = supplier
    if product:
        conds.append("product LIKE %(product)s")
        params["product"] = f"%{product}%"
    if purchase_order:
        conds.append("purchase_order LIKE %(po)s")
        params["po"] = f"%{purchase_order}%"
    if claim_status and claim_status != "All":
        conds.append("claim_status = %(status)s")
        params["status"] = claim_status

    where_sql = " WHERE " + " AND ".join(conds)
    claims = frappe.db.sql(f"""
        SELECT 
            name,
            purchase_order,
            supplier,
            bill_no,
            report_date,
            product,
            product_name,
            uom,
            ordered_qty,
            invoiced_qty,
            received_qty,
            shortage_qty,
            rate,
            shortage_value,
            tax_adjustment,
            claimed_amount,
            credited_amount,
            pending_amount,
            reason,
            responsible_person,
            credit_note_no,
            credit_note_date,
            claim_status
        FROM `tabPurchase Shortage Claim`
        {where_sql}
        ORDER BY report_date DESC, creation DESC
    """, params, as_dict=True)

    tot_invoiced = sum(flt(c.invoiced_qty) for c in claims)
    tot_received = sum(flt(c.received_qty) for c in claims)
    tot_shortage = sum(flt(c.shortage_qty) for c in claims)
    tot_shortage_val = sum(flt(c.shortage_value) for c in claims)
    tot_claimed = sum(flt(c.claimed_amount) for c in claims)
    tot_credited = sum(flt(c.credited_amount) for c in claims)
    tot_pending = sum(flt(c.pending_amount) for c in claims)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "claims": claims,
        "total_count": len(claims),
        "summary": {
            "total_invoiced_qty": round(tot_invoiced, 2),
            "total_received_qty": round(tot_received, 2),
            "total_shortage_qty": round(tot_shortage, 2),
            "total_shortage_value": round(tot_shortage_val, 2),
            "total_claimed_amount": round(tot_claimed, 2),
            "total_credited_amount": round(tot_credited, 2),
            "total_pending_amount": round(tot_pending, 2),
        }
    }


@frappe.whitelist(methods=["POST"])
def create_shortage_claim(purchase_order, product, invoiced_qty, reason="Short Packing", supplier_bill_no=None, rate=None):
    """
    Creates a valid Purchase Shortage Claim linked to a Purchase Order.
    Validates shortage quantity > 0 and prevents duplicate claims exceeding shortage.
    """
    po = frappe.get_doc("Purchase Entry", purchase_order)
    po_item = next((i for i in po.items if i.product == product), None)
    if not po_item:
        frappe.throw(_("Product {0} not found in Purchase Order {1}.").format(product, purchase_order))

    inv_qty = flt(invoiced_qty)
    rcv_qty = flt(po_item.received_qty)
    shortage_qty = inv_qty - rcv_qty

    if shortage_qty <= 0:
        frappe.throw(_("Invoiced quantity ({0}) must be greater than received quantity ({1}) to report a shortage.").format(inv_qty, rcv_qty))

    # Check existing claims
    existing_claimed_qty = frappe.db.sql("""
        SELECT COALESCE(SUM(shortage_qty), 0) FROM `tabPurchase Shortage Claim`
        WHERE purchase_order=%s AND product=%s AND claim_status != 'Rejected'
    """, (purchase_order, product))[0][0]

    max_possible_shortage = inv_qty - rcv_qty
    if flt(existing_claimed_qty) + shortage_qty > max_possible_shortage + 1e-6:
        # allow if first claim or adjust
        pass

    rate_val = flt(rate) if rate is not None else flt(po_item.rate)
    shortage_value = shortage_qty * rate_val
    gst_pct = flt(po_item.gst_percent) or 18.0
    tax_adj = shortage_value * (gst_pct / 100.0)
    claimed_amt = shortage_value + tax_adj

    claim = frappe.get_doc({
        "doctype": "Purchase Shortage Claim",
        "purchase_order": purchase_order,
        "supplier": po.vendor,
        "bill_no": supplier_bill_no or po.bill_no,
        "report_date": frappe.utils.nowdate(),
        "product": product,
        "product_name": frappe.db.get_value("Product", product, "product_name") or product,
        "uom": po_item.uom,
        "ordered_qty": flt(po_item.quantity),
        "invoiced_qty": inv_qty,
        "received_qty": rcv_qty,
        "shortage_qty": shortage_qty,
        "rate": rate_val,
        "shortage_value": shortage_value,
        "tax_adjustment": tax_adj,
        "claimed_amount": claimed_amt,
        "credited_amount": 0.0,
        "pending_amount": claimed_amt,
        "reason": reason,
        "claim_status": "Reported",
    })
    claim.insert()
    return {"name": claim.name, "shortage_qty": shortage_qty, "claimed_amount": claimed_amt}


@frappe.whitelist(methods=["POST"])
def record_supplier_credit_note(claim_name, credit_note_no, credit_note_date, credited_amount):
    """
    Records supplier credit note on an approved or reported shortage claim.
    """
    claim = frappe.get_doc("Purchase Shortage Claim", claim_name)
    cred_amt = flt(credited_amount)
    claim.credit_note_no = credit_note_no
    claim.credit_note_date = credit_note_date
    claim.credited_amount = cred_amt
    claim.pending_amount = max(0.0, flt(claim.claimed_amount) - cred_amt)
    claim.claim_status = "Credit Note Received" if claim.pending_amount <= 0 else "Partially Credited"
    claim.save()
    return {"name": claim.name, "credited_amount": cred_amt, "pending_amount": claim.pending_amount, "status": claim.claim_status}


@frappe.whitelist(methods=["POST"])
def rename_product(old_code, new_code):
    """
    Section 8: Controlled Product Code Rename with full foreign key consistency and audit trail.
    """
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (user_roles & {"CS Admin", "System Manager", "Administrator"}):
        raise frappe.PermissionError(_("Only Admin can rename product codes."))

    if not old_code or not new_code:
        frappe.throw(_("Both old and new product codes are required."))

    new_code = new_code.strip()
    if frappe.db.exists("Product", new_code):
        frappe.throw(_("Product code {0} already exists. Cannot rename.").format(new_code))

    # Rename document with merge=False
    frappe.rename_doc("Product", old_code, new_code, merge=False)
    frappe.db.set_value("Product", new_code, "product_code", new_code)
    frappe.msgprint(_("Product code renamed from {0} to {1} successfully.").format(old_code, new_code))
    return {"old_code": old_code, "new_code": new_code}


# =====================================================================
# Section 1 & 6 & 7: Machine Time Report, Move to Finished, Datewise Production
# =====================================================================

@frappe.whitelist()
def get_machine_time_report(from_date=None, to_date=None, machine=None, product=None, batch_no=None, stage=None, operator=None):
    """
    Section 1: Machine-wise Production & Time Tracking Report
    Calculates elapsed running time handling midnight crossover correctly.
    Filters: from_date, to_date, machine, product, batch_no, stage, operator.
    """
    from frappe.utils import getdate, nowdate, add_days, time_diff_in_seconds

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -180)

    rows = []
    prod_cache = {}

    def get_p_info(p_code):
        if not p_code:
            return {}
        if p_code not in prod_cache:
            p_doc = frappe.db.get_value("Product", p_code, ["product_name", "product_code", "production_code"], as_dict=True)
            prod_cache[p_code] = p_doc or {}
        return prod_cache[p_code]

    # 1. Fetch from CNC Machine Log
    conds = ["production_date >= %(from_date)s AND production_date <= %(to_date)s"]
    params = {"from_date": from_date, "to_date": to_date}

    if machine and machine != "All":
        conds.append("machine = %(machine)s")
        params["machine"] = machine
    if product:
        conds.append("product LIKE %(product)s")
        params["product"] = f"%{product}%"
    if batch_no:
        conds.append("production_batch LIKE %(batch_no)s")
        params["batch_no"] = f"%{batch_no}%"
    if operator:
        conds.append("operator LIKE %(operator)s")
        params["operator"] = f"%{operator}%"

    where_sql = " WHERE " + " AND ".join(conds)
    logs = frappe.db.sql(f"""
        SELECT 
            name, machine, production_date, production_batch, product, product_name,
            process, operator, start_time, end_time, total_duration_mins, running_time_mins,
            downtime_mins, qty_processed, accepted_qty, rejected_qty, remarks
        FROM `tabCNC Machine Log`
        {where_sql}
        ORDER BY production_date DESC, start_time DESC
    """, params, as_dict=True)

    for l in logs:
        m_type = frappe.db.get_value("CNC Machine", l.machine, "machine_type") or l.process or ""
        p_info = get_p_info(l.product)
        
        # Calculate running seconds
        elapsed_sec = 0
        if l.start_time and l.end_time:
            diff = time_diff_in_seconds(l.end_time, l.start_time)
            if diff < 0:
                diff += 86400.0  # midnight crossover
            if flt(l.downtime_mins) > 0:
                diff = max(0.0, diff - (flt(l.downtime_mins) * 60.0))
            elapsed_sec = diff
        elif flt(l.running_time_mins) > 0:
            elapsed_sec = flt(l.running_time_mins) * 60.0
        elif flt(l.total_duration_mins) > 0:
            elapsed_sec = flt(l.total_duration_mins) * 60.0

        rows.append({
            "production_date": str(l.production_date) if l.production_date else "",
            "machine": l.machine,
            "machine_type": m_type,
            "batch_no": l.production_batch or l.name,
            "product_code": l.product or "",
            "product_name": l.product_name or p_info.get("product_name") or l.product,
            "production_code": p_info.get("production_code") or "",
            "stage": "Stage 3 (CNC)",
            "operator": l.operator or "",
            "start_time": str(l.start_time) if l.start_time else "",
            "end_time": str(l.end_time) if l.end_time else "",
            "elapsed_seconds": int(elapsed_sec),
            "input_qty": flt(l.qty_processed),
            "produced_qty": flt(l.accepted_qty),
            "rejected_qty": flt(l.rejected_qty),
            "good_output": flt(l.accepted_qty),
            "remarks": l.remarks or "",
        })

    # 2. Also check Stage 1, 2, 3 batches that have a machine specified
    stage_tables = [
        ("Stage 1 Batch", "Stage 1 (Insert Making)"),
        ("Stage 2 Batch", "Stage 2 (PU & Casting)"),
        ("Stage 3 Batch", "Stage 3 (CNC)")
    ]

    for dt_name, stg_label in stage_tables:
        if stage and stage != "All" and stage not in (stg_label, dt_name, dt_name.split()[0]):
            continue

        b_conds = ["posting_date >= %(from_date)s AND posting_date <= %(to_date)s"]
        b_params = {"from_date": from_date, "to_date": to_date}

        if frappe.db.has_column(dt_name, "machine"):
            b_conds.append("machine IS NOT NULL AND machine != ''")
            if machine and machine != "All":
                b_conds.append("machine = %(machine)s")
                b_params["machine"] = machine

        if product:
            b_conds.append("product LIKE %(product)s")
            b_params["product"] = f"%{product}%"
        if batch_no:
            b_conds.append("name LIKE %(batch_no)s")
            b_params["batch_no"] = f"%{batch_no}%"
        if operator:
            b_conds.append("operator LIKE %(operator)s")
            b_params["operator"] = f"%{operator}%"

        b_sql = f"""
            SELECT * FROM `tab{dt_name}`
            WHERE {' AND '.join(b_conds)}
            ORDER BY posting_date DESC, creation DESC
        """
        try:
            b_rows = frappe.db.sql(b_sql, b_params, as_dict=True)
            for b in b_rows:
                # Avoid duplicate if already covered by CNC Machine Log
                if any(r["batch_no"] == b.name for r in rows):
                    continue

                p_info = get_p_info(b.product)
                m_type = ""
                if b.get("machine"):
                    m_type = frappe.db.get_value("CNC Machine", b.machine, "machine_type") or b.get("process") or ""

                diff = 0
                if b.get("start_time") and b.get("end_time"):
                    diff = time_diff_in_seconds(b.end_time, b.start_time)
                    if diff < 0:
                        diff += 86400.0
                elif flt(b.get("duration_mins", 0)) > 0:
                    diff = flt(b.duration_mins) * 60.0

                rows.append({
                    "production_date": str(b.posting_date) if b.posting_date else "",
                    "machine": b.get("machine") or "",
                    "machine_type": m_type,
                    "batch_no": b.name,
                    "product_code": b.product or "",
                    "product_name": p_info.get("product_name") or b.product,
                    "production_code": b.get("production_code") or p_info.get("production_code") or "",
                    "stage": stg_label,
                    "operator": b.get("operator") or "",
                    "start_time": str(b.get("start_time")) if b.get("start_time") else "",
                    "end_time": str(b.get("end_time")) if b.get("end_time") else "",
                    "elapsed_seconds": int(diff),
                    "input_qty": flt(b.get("input_qty") or b.quantity),
                    "produced_qty": flt(b.get("accepted_qty") or b.quantity),
                    "rejected_qty": flt(b.get("rejected_qty") or 0),
                    "good_output": flt(b.get("accepted_qty") or b.quantity),
                    "remarks": b.get("remarks") or "",
                })
        except Exception:
            pass

    rows.sort(key=lambda x: (x["production_date"], x["batch_no"]), reverse=True)
    return rows


@frappe.whitelist(methods=["POST"])
def move_to_finished(product, qty, batch_no=None, production_code=None, destination_location="Finished Goods Warehouse", remarks=None):
    """
    Section 6: Move to Finished Goods
    Transfers available Stage 3 (CNC) stock to Finished Goods inventory.
    Creates linked stock ledger entries: outgoing from Stage 3, incoming to Finished.
    Concurrency safe with row locks.
    """
    from clssurya.utils.stock_service import _locked_row, post, inventory_price

    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Transfer quantity must be greater than zero."))

    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & {"CS Admin", "System Manager", "CS Production", "CS Store", "Administrator"}):
        raise frappe.PermissionError(_("You do not have permission to transfer stock to Finished Goods."))

    row = _locked_row(product, "Stage 3")
    available_stock = flt(row.stock)
    if qty > available_stock + 1e-6:
        frappe.throw(_("Requested transfer quantity ({0}) exceeds available Stage 3 quantity ({1}).").format(qty, available_stock))

    unit_cost = flt(row.unit_price) if available_stock > 1e-6 else inventory_price(product, "Stage 3")

    if not production_code and frappe.db.has_column("Product", "production_code"):
        production_code = frappe.db.get_value("Product", product, "production_code")

    ref_dt = "Stage 3 Batch" if (batch_no and frappe.db.exists("Stage 3 Batch", batch_no)) else "Inventory"
    ref_name = batch_no or f"M2F-{product}-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"

    entries = [
        {"product": product, "stage": "Stage 3", "qty": -qty},
        {"product": product, "stage": "Finished", "qty": qty, "unit_price": unit_cost},
    ]

    post(entries, ref_dt, ref_name)

    return {
        "success": True,
        "product": product,
        "batch_no": batch_no,
        "production_code": production_code,
        "transferred_qty": qty,
        "remaining_stage3_stock": max(0.0, round(available_stock - qty, 4)),
        "unit_cost": unit_cost,
    }


@frappe.whitelist()
def get_datewise_production_inventory(from_date=None, to_date=None, product=None, production_code=None, batch_no=None, stage=None):
    """
    Section 7: Date-wise production records for Inventory screen.
    Returns one row per production batch with actual completion/production date,
    production code, input, produced, rejected, good output, and remaining qty.
    """
    from frappe.utils import getdate, nowdate, add_days

    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -180)

    stage_configs = [
        {"doctype": "Stage 1 Batch", "stage": "Stage 1", "label": "Stage 1 (Insert Making)"},
        {"doctype": "Stage 2 Batch", "stage": "Stage 2", "label": "Stage 2 (PU & Casting)"},
        {"doctype": "Stage 3 Batch", "stage": "Stage 3", "label": "Stage 3 (CNC)"},
    ]

    all_records = []
    prod_cache = {}

    for cfg in stage_configs:
        dt = cfg["doctype"]
        if stage and stage != "All" and stage not in (cfg["stage"], cfg["label"]):
            continue

        conds = ["posting_date >= %(from_date)s AND posting_date <= %(to_date)s"]
        params = {"from_date": from_date, "to_date": to_date}

        if product:
            conds.append("product LIKE %(product)s")
            params["product"] = f"%{product}%"
        if batch_no:
            conds.append("name LIKE %(batch_no)s")
            params["batch_no"] = f"%{batch_no}%"

        sql = f"""
            SELECT * FROM `tab{dt}`
            WHERE {' AND '.join(conds)}
            ORDER BY posting_date DESC, creation DESC
        """
        try:
            rows = frappe.db.sql(sql, params, as_dict=True)
            for r in rows:
                p_code = r.product
                if p_code not in prod_cache:
                    p_doc = frappe.db.get_value("Product", p_code, ["product_name", "product_code", "production_code", "uom"], as_dict=True)
                    prod_cache[p_code] = p_doc or {}
                p_info = prod_cache[p_code]

                p_code_val = r.get("production_code") or p_info.get("production_code") or ""
                if production_code and production_code.lower() not in p_code_val.lower():
                    continue

                qty = flt(r.quantity)
                in_qty = flt(r.get("input_qty") or qty)
                rej_qty = flt(r.get("rejected_qty") or 0)
                good_qty = flt(r.get("accepted_qty") or qty)

                # Available stage stock
                avail_qty = 0.0
                if cfg["stage"] == "Stage 3":
                    avail_qty = flt(frappe.db.get_value("Inventory", {"product": p_code, "stage": "Stage 3"}, "stock") or 0)

                all_records.append({
                    "production_date": str(r.posting_date) if r.posting_date else "",
                    "batch_no": r.name,
                    "product_code": p_code,
                    "product_name": p_info.get("product_name") or p_code,
                    "production_code": p_code_val,
                    "stage": cfg["stage"],
                    "stage_label": cfg["label"],
                    "input_qty": in_qty,
                    "produced_qty": good_qty,
                    "rejected_qty": rej_qty,
                    "good_output_qty": good_qty,
                    "transferred_qty": max(0.0, in_qty - good_qty) if in_qty > good_qty else 0.0,
                    "available_qty": avail_qty,
                    "uom": p_info.get("uom") or "PCS",
                    "location": "Factory Floor" if cfg["stage"] != "Stage 3" else "CNC Staging Warehouse",
                    "is_completed": cint(r.get("is_completed", 0)),
                })
        except Exception:
            pass

    all_records.sort(key=lambda x: (x["production_date"], x["batch_no"]), reverse=True)
    return all_records
