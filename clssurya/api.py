import frappe
from frappe import _
from frappe.utils import cint, flt

from clssurya.constants import COMPLETABLE, MASTERS
from clssurya.utils.base import is_admin
from clssurya.utils.stock_service import inventory_price
from clssurya.utils.versions import get_versions

ACTIONS = {
    **{dt: {"complete", "reopen"} for dt in COMPLETABLE},
    "Quotation": {"revise", "make_sales_order", "approve"},
    "Sales Order": {"approve", "create_dispatch"},
    "Dispatch": {"create_from_sales_order", "complete", "reopen", "cancel"},
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
    ``args`` is an optional dict for custom actions (e.g., creating a Dispatch).
    """
    if not action:
        frappe.throw(_("Action is required"), frappe.ValidationError)
    if action not in ACTIONS.get(doctype, set()):
        frappe.throw(_(f"Action {action} is not allowed on {doctype}."), frappe.PermissionError)

    # Special case: create Dispatch from a Sales Order (no existing Dispatch doc)

    # Special case: create Dispatch from an approved Sales Order
    if doctype == "Dispatch" and action == "create_from_sales_order":
        if not args or not args.get("sales_order"):
            frappe.throw(
                _("sales_order argument is required"),
                frappe.ValidationError,
            )

        sales_order = args["sales_order"]
        so = frappe.get_doc("Sales Order", sales_order)

        if so.status not in ("Approved", "Partially Dispatched"):
            frappe.throw(
                _("Sales Order must be Approved or Partially Dispatched."),
                frappe.ValidationError,
            )

        disp = frappe.new_doc("Dispatch")
        disp.sales_order = so.name
        disp.customer = so.customer
        disp.dispatch_date = frappe.utils.nowdate()

        # Populate Dispatch items BEFORE insert/validation
        for item in so.items:
            ordered_qty = flt(item.quantity)
            dispatched_qty = flt(item.dispatched_qty)

            pending_qty = ordered_qty - dispatched_qty

            if pending_qty > 0:
                disp.append("items", {
                    "order_item": item.name,
                    "product": item.product,
                    "ordered_qty": ordered_qty,
                    "already_dispatched": dispatched_qty,
                    "quantity": pending_qty,
                    "unit_cost": flt(item.rate),
                })

        if not disp.items:
            # No pending items – return a friendly message instead of raising an error
            return {"name": None, "result": "No pending items to dispatch for this Sales Order."}

        # Insert only after all item rows have been added
        disp.insert()

        return {
            "name": disp.name,
            "result": "Dispatch created",
        }

    # Normal path: existing document
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    method = getattr(doc, action)
    result = method(**(args or {}))
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
