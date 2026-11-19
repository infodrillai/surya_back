import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate, getdate

from clssurya.constants import COMPLETABLE, MASTERS
from clssurya.utils.base import is_admin, require_admin
from clssurya.utils.sales_person import get_current_sales_person, is_sales_person
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
    user = frappe.session.user
    if not user or user == "Guest":
        return []
    if is_admin(user):
        return MASTERS
    return [dt for dt in MASTERS if dt in ("Currency", "UOM") or frappe.has_permission(dt, "read")]


@frappe.whitelist(allow_guest=True)
def get_csrf_token():
    return frappe.sessions.get_csrf_token()


@frappe.whitelist(allow_guest=True)
def me():
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("Authentication required"), frappe.AuthenticationError)
    sp = get_current_sales_person(user)
    roles = frappe.get_roles(user)
    return {
        "user": user,
        "full_name": frappe.utils.get_fullname(user),
        "roles": roles,
        "is_admin": is_admin(user),
        "is_sales_person": is_sales_person(user),
        "is_store_executive": "Store Executive" in roles,
        "is_pu_operator": "PU Operator" in roles,
        "is_belt_operator": "Belt Operator" in roles,
        "sales_person": sp,
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
def get_stage_rows(product, qty, stage, size=None):
    """BOM rows for a batch: per-unit utilization, total utilization, amount, per-unit amount."""
    if not frappe.has_permission(f"Stage {cint(stage)} Batch", "read"):
        raise frappe.PermissionError
    stage, qty = cint(stage), flt(qty)
    bom = frappe.get_doc("BOM", product)
    if cint(bom.total_steps) < stage:
        frappe.throw(_("{0} has only {1} step(s) in its BOM.").format(product, bom.total_steps))

    prod_doc = frappe.db.get_value("Product", product, ["product_type", "finished_good_type", "band_type", "belt_length", "hole"], as_dict=True)
    is_belt = bool(prod_doc and prod_doc.product_type == "Finished" and prod_doc.finished_good_type == "Belt")

    def row(**kw):
        per, price = flt(kw["per_unit_utilization"]), flt(kw["unit_price"])
        total = per * qty
        return {**kw, "total_utilization": total, "actual_utilization": total, "amount": total * price,
                "per_unit_amount": per * price, "actual_amount": total * price, "extra_cost": flt(kw.get('extra_cost', 0))}

    out = {"items": [], "charges": [], "wastage_product": None}
    if stage > 1:
        if is_belt and stage == 2:
            # Belt Stage 2 does not carry in the Belt product; it consumes Roll from Stage 1
            pass
        else:
            prev = "Stage 1" if stage == 2 else "Stage 2"
            out["items"].append(row(is_carried_in=1, process=None, product=product, per_unit_utilization=1,
                                    unit_price=inventory_price(product, prev), source_stage=prev))
    if stage == 1:
        for r in bom.stage1_items:
            out["wastage_product"] = out["wastage_product"] or r.wastage_product
            out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                    per_unit_utilization=r.per_unit_utilization, unit_price=inventory_price(r.product, "Raw"),
                                    source_stage="Raw"))
    elif stage == 2:
        if is_belt:
            if size is not None and flt(size) > 0:
                s_val = flt(size)
            else:
                length_mm = flt(prod_doc.belt_length) if (prod_doc and prod_doc.belt_length) else 0.0
                band = (prod_doc.band_type or "") if prod_doc else ""
                if "Grommed" in band:
                    if 1080 <= length_mm <= 1120:
                        s_val = 1.2
                    elif 1460 <= length_mm <= 1510:
                        s_val = 1.5
                    elif length_mm > 0:
                        s_val = round(length_mm / 1000.0, 3)
                    else:
                        s_val = 1.0
                else:  # Lower / Upper
                    s_val = round(length_mm / 1000.0, 3) if length_mm > 0 else 1.0
            out["default_size"] = s_val
            for r in bom.stage2_items:
                ratio_val = flt(r.ratio) if flt(r.ratio) > 0 else 1.0
                per_u = s_val / ratio_val
                roll_price = inventory_price(r.product, "Stage 1") or inventory_price(r.product, "Raw")
                out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                        per_unit_utilization=per_u, unit_price=roll_price,
                                        ratio=ratio_val, source_stage="Stage 1"))
        else:
            for r in bom.stage2_items:
                out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                        per_unit_utilization=r.per_unit_utilization, unit_price=inventory_price(r.product, "Raw"),
                                        source_stage="Raw"))
    else:
        if is_belt:
            hole_count = flt(prod_doc.hole) if (prod_doc and prod_doc.hole) else 0.0
            for r in (bom.get("stage3_items") or []):
                ratio_val = flt(r.ratio) or 1.0
                calc_type = r.calculation_type or "Quantity"
                if calc_type == "Hole":
                    per_u = hole_count * ratio_val
                else:
                    per_u = ratio_val
                comp_price = inventory_price(r.product, "Raw")
                out["items"].append(row(is_carried_in=0, process=r.process, product=r.product,
                                        per_unit_utilization=per_u, unit_price=comp_price,
                                        ratio=ratio_val, calculation_type=calc_type, source_stage="Raw"))
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
    """Finished stock and production cost per unit. Open to Sales (they cannot read the ledger).
    Returns accurate unit cost for all products (PU, Belt, Finished goods) by checking:
    1. Inventory (Finished / Stage 3 / Stage 2)
    2. Latest Stage 3, Stage 2, Stage 1 Batches
    3. Latest Belt Batches
    4. BOM standard cost calculation
    Indexed by product name, product code, production code, and product name.
    """
    out = {}

    # 1. BOM-based calculation for all finished/semi products
    try:
        boms = frappe.get_all("BOM", fields=["name", "product", "total_steps"])
        for b in boms:
            prod = b.product
            try:
                bom_doc = frappe.get_doc("BOM", b.name)
                p_info = frappe.db.get_value("Product", prod, ["finished_good_type", "belt_length", "hole"], as_dict=True) or {}
                is_belt = (p_info.get("finished_good_type") == "Belt")

                if is_belt:
                    s1 = sum(flt(r.per_unit_utilization) * (flt(frappe.db.get_value("Inventory", {"product": r.product, "stage": "Raw"}, "unit_price")) or 0) for r in (bom_doc.stage1_items or []))
                    s2 = sum(flt(r.per_unit_utilization) * (flt(frappe.db.get_value("Inventory", {"product": r.product, "stage": "Raw"}, "unit_price")) or 0) for r in (bom_doc.stage2_items or []))
                    s3 = sum(flt(r.per_unit_utilization) * (flt(frappe.db.get_value("Inventory", {"product": r.product, "stage": "Raw"}, "unit_price")) or 0) for r in (bom_doc.get("stage3_items") or []))
                    chg = sum(flt(c.per_unit_price) for c in (bom_doc.stage3_charges or []))
                    bom_cost = round(s1 + s2 + s3 + chg, 4)
                else:
                    s1 = sum(flt(r.per_unit_utilization) * (flt(frappe.db.get_value("Inventory", {"product": r.product, "stage": "Raw"}, "unit_price")) or 0) for r in (bom_doc.stage1_items or []))
                    s2 = sum(flt(r.per_unit_utilization) * (flt(frappe.db.get_value("Inventory", {"product": r.product, "stage": "Raw"}, "unit_price")) or 0) for r in (bom_doc.stage2_items or []))
                    rej = (s1 + s2) * 0.10
                    chg = sum(flt(c.per_unit_price) for c in (bom_doc.stage3_charges or []))
                    bom_cost = round(s1 + s2 + rej + chg, 4)

                if bom_cost > 0:
                    out[prod] = {"stock": 0.0, "unit_price": bom_cost, "source": "BOM"}
            except Exception:
                pass
    except Exception:
        pass

    # 2. Stage Batches (Stage 1 -> Stage 2 -> Stage 3)
    for dt in ["Stage 1 Batch", "Stage 2 Batch", "Stage 3 Batch"]:
        try:
            if frappe.db.exists("DocType", dt):
                batches = frappe.db.sql(f"""
                    SELECT product, production_code, unit_cost, batch_total, quantity
                    FROM `tab{dt}`
                    WHERE unit_cost > 0 OR (quantity > 0 AND batch_total > 0)
                    ORDER BY modified ASC
                """, as_dict=True)
                for b in batches:
                    c = flt(b.unit_cost) or ((flt(b.batch_total) / flt(b.quantity)) if flt(b.quantity) > 0 else 0)
                    if c > 0:
                        if b.product:
                            out[b.product] = {"stock": 0.0, "unit_price": round(c, 4), "source": dt}
                        if b.production_code:
                            out[b.production_code] = {"stock": 0.0, "unit_price": round(c, 4), "source": dt}
        except Exception:
            pass

    # 3. Belt Batches
    try:
        if frappe.db.exists("DocType", "Belt Batch"):
            b_batches = frappe.db.sql("""
                SELECT product, unit_cost, batch_total, quantity
                FROM `tabBelt Batch`
                WHERE unit_cost > 0 OR (quantity > 0 AND batch_total > 0)
                ORDER BY modified ASC
            """, as_dict=True)
            for b in b_batches:
                c = flt(b.unit_cost) or ((flt(b.batch_total) / flt(b.quantity)) if flt(b.quantity) > 0 else 0)
                if c > 0 and b.product:
                    out[b.product] = {"stock": 0.0, "unit_price": round(c, 4), "source": "Belt Batch"}
    except Exception:
        pass

    # 4. Inventory records (Stage 2 -> Stage 3 -> Finished)
    try:
        inv_rows = frappe.get_all("Inventory", filters={"stage": ["in", ["Stage 2", "Stage 3", "Finished"]]}, fields=["product", "stage", "stock", "unit_price"])
        # Sort so Finished overrides Stage 3 which overrides Stage 2
        order_map = {"Stage 2": 1, "Stage 3": 2, "Finished": 3}
        inv_rows.sort(key=lambda x: order_map.get(x.stage, 0))
        for r in inv_rows:
            if flt(r.unit_price) > 0:
                out[r.product] = {"stock": flt(r.stock), "unit_price": round(flt(r.unit_price), 4), "source": f"Inventory {r.stage}"}
    except Exception:
        pass

    # 5. Mirror keys for product_code, product_name, and production_code
    try:
        all_prods = frappe.db.sql("SELECT name, product_code, product_name, production_code FROM `tabProduct`", as_dict=True)
        for p in all_prods:
            base_info = out.get(p.name) or out.get(p.product_code) or out.get(p.product_name) or out.get(p.production_code)
            if base_info:
                if p.product_code and p.product_code not in out:
                    out[p.product_code] = base_info
                if p.product_name and p.product_name not in out:
                    out[p.product_name] = base_info
                if p.production_code and p.production_code not in out:
                    out[p.production_code] = base_info
    except Exception:
        pass

    return out


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

        p_info = frappe.db.get_value("Product", item.product, ["product_type", "finished_good_type", "hole", "belt_length"], as_dict=True)
        if p_info and p_info.product_type == "Finished" and p_info.finished_good_type == "Belt":
            # 1. Roll material item from stage 2
            roll_items = []
            roll_unit = 0.0
            for r in bom.stage2_items:
                r_rate = inventory_price(r.product, "Stage 1") or default_prices.get(r.product, 0)
                ratio_val = flt(r.ratio) or 1.0
                len_val = flt(p_info.belt_length) or 1.0
                u = (len_val / ratio_val) * r_rate
                roll_items.append({
                    "name": raw_labels.get(r.product, f"Roll ({r.product})"),
                    "code": r.product,
                    "category": "Material",
                    "per_unit": u,
                    "color": "#6366f1",
                })
                roll_unit += u

            rejection_pct = 5.0
            latest_s2b = frappe.db.get_value("Stage 2 Batch", {"product": item.product, "is_completed": 1}, "rejection_percent")
            if latest_s2b is not None:
                rejection_pct = flt(latest_s2b)

            rejection_unit = roll_unit * (rejection_pct / 100.0)
            s2_total_unit = roll_unit + rejection_unit

            if item.stage == "Stage 2":
                scale = (unit_price / s2_total_unit) if (s2_total_unit and abs(unit_price - s2_total_unit) > 0.001) else 1.0
                comps = []
                for it in roll_items:
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

            # Stage 3 or Finished Stage for Belt
            comp_items = []
            comp_unit = 0.0
            hole_cnt = flt(p_info.hole) if p_info.hole else 0.0
            for r in (bom.get("stage3_items") or []):
                rate = inventory_price(r.product, "Raw") or default_prices.get(r.product, 0)
                calc_type = r.calculation_type or "Quantity"
                ratio_val = flt(r.ratio) or 1.0
                u = (hole_cnt * ratio_val * rate) if calc_type == "Hole" else (ratio_val * rate)
                comp_items.append({
                    "name": raw_labels.get(r.product, r.product),
                    "code": r.product,
                    "category": "Material",
                    "per_unit": u,
                    "color": "#0ea5e9",
                })
                comp_unit += u

            s3_charges = []
            s3_charge_unit = 0.0
            for c in bom.stage3_charges:
                pu = flt(c.per_unit_price)
                s3_charges.append({
                    "name": c.charge,
                    "code": c.charge,
                    "category": "Charge",
                    "per_unit": pu,
                    "color": charge_colors.get(c.charge, "#10b981"),
                })
                s3_charge_unit += pu

            full_unit = roll_unit + comp_unit + s3_charge_unit + rejection_unit
            scale = (unit_price / full_unit) if (full_unit and abs(unit_price - full_unit) > 0.001) else 1.0

            comps = []
            for it in [*roll_items, *comp_items]:
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
                    "cnc": {"name": "CNC Repair & Tooling", "amount": 0.0, "unit_rate": 0.0, "percent": 0.0, "color": "#10b981"},
                    "admin": {"name": "Admin Expense", "amount": admin_tot, "unit_rate": round(admin_tot / stock, 2) if stock else 0, "percent": round(admin_tot / total_amount * 100, 1) if total_amount else 0, "color": "#64748b"},
                },
                "components": comps,
            }
            continue

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
    """Return all Goods Receipt records linked to a Purchase Order with accurate cost and total value."""
    if not frappe.has_permission("Goods Receipt", "read"):
        raise frappe.PermissionError

    po_items_by_name = {}
    po_items_by_product = {}
    try:
        po = frappe.get_doc("Purchase Entry", purchase_order)
        for line in po.items:
            po_items_by_name[line.name] = line
            po_items_by_product.setdefault(line.product, line)
    except Exception:
        pass

    receipts = frappe.get_all(
        "Goods Receipt",
        filters={"purchase_order": purchase_order},
        fields=["name", "posting_date", "status", "supplier_delivery_note", "remarks", "total_qty", "total_amount", "confirmed_on", "confirmed_by"],
        order_by="creation desc",
    )
    result = []
    for r in receipts:
        doc = frappe.get_doc("Goods Receipt", r.name)
        items_list = []
        gr_total_amount = 0.0
        gr_total_qty = 0.0
        for row in doc.items:
            po_line = po_items_by_name.get(row.purchase_order_item) or po_items_by_product.get(row.product)
            po_rate = flt(po_line.rate) if po_line else 0.0
            po_landed_rate = flt(po_line.landed_rate) if (po_line and flt(po_line.landed_rate)) else po_rate

            rcv_qty = flt(row.received_qty)
            rate = flt(row.rate) or po_rate
            landed_rate = flt(row.landed_rate) or po_landed_rate or rate
            cost = landed_rate or rate
            amount = flt(row.amount)
            if not amount and rcv_qty:
                amount = rcv_qty * cost

            gr_total_qty += rcv_qty
            gr_total_amount += amount

            # Auto-repair row in db if it was stored with 0 cost
            if (flt(row.rate) == 0 or flt(row.amount) == 0) and r.status == "Confirmed" and cost > 0:
                try:
                    frappe.db.set_value(
                        "Goods Receipt Item",
                        row.name,
                        {
                            "rate": rate,
                            "landed_rate": landed_rate,
                            "amount": amount,
                            "uom": row.uom or (po_line.uom if po_line else "Unit"),
                        },
                        update_modified=False,
                    )
                except Exception:
                    pass

            items_list.append({
                "purchase_order_item": row.purchase_order_item,
                "product": row.product,
                "product_name": row.product_name or frappe.db.get_value("Product", row.product, "product_name") or (po_line.product_name if po_line else row.product),
                "uom": row.uom or (po_line.uom if po_line else frappe.db.get_value("Product", row.product, "uom")) or "Unit",
                "ordered_qty": flt(row.ordered_qty) or (flt(po_line.quantity) if po_line else 0.0),
                "already_received_qty": flt(row.already_received_qty),
                "pending_qty": flt(row.pending_qty),
                "received_qty": rcv_qty,
                "rate": rate,
                "landed_rate": landed_rate,
                "cost": cost,
                "amount": amount,
            })

        r["items"] = items_list
        if not flt(r.get("total_amount")) and gr_total_amount:
            r["total_amount"] = gr_total_amount
            if r.status == "Confirmed":
                try:
                    frappe.db.set_value("Goods Receipt", r.name, "total_amount", gr_total_amount, update_modified=False)
                except Exception:
                    pass
        if not flt(r.get("total_qty")) and gr_total_qty:
            r["total_qty"] = gr_total_qty

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
            conds.append("operation LIKE %(process)s")
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
                operation,
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
                "process_name": r.operation or "",
                "operation": r.operation or "",
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
    Aggregates:
      - Product Name and Product Code
      - Stage 1 Produced Quantity
      - Stage 2 Produced Quantity
      - Stage 3 Produced Quantity
      - Total Produced Quantity (from final completed production stage without double counting)
      - Total Dispatched/Sold Quantity (from confirmed dispatches in period)
      - Customer Return Quantity (from confirmed customer returns in period)
      - Remaining Available Inventory (current Finished goods stock)
      - Historical rejection and production cost incurred in period
    """
    import datetime
    from frappe.utils import getdate, nowdate, add_months, cint, flt

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
                    "total_steps": cint(doc.get("total_steps") or 3),
                    "product_type": doc.get("product_type") or "Finished",
                }
            except Exception:
                product_cache[p_id] = {
                    "product_name": p_id,
                    "product_code": p_id,
                    "production_code": "",
                    "uom": "PCS",
                    "total_steps": 3,
                    "product_type": "Finished",
                }
        return product_cache[p_id]

    try:
        prods = frappe.get_all(
            "Product",
            fields=["name", "product_name", "product_code", "production_code", "uom", "total_steps", "product_type"],
            ignore_permissions=True,
        )
        for p in prods:
            product_cache[p["name"]] = {
                "product_name": p.get("product_name") or p["name"],
                "product_code": p.get("product_code") or p["name"],
                "production_code": p.get("production_code") or "",
                "uom": p.get("uom") or "PCS",
                "total_steps": cint(p.get("total_steps") or 3),
                "product_type": p.get("product_type") or "Finished",
            }
    except Exception:
        pass

    # 2. Stage Batches Query
    # Rules 4 & 5:
    # Do not count pending or unconfirmed production batches as completed production.
    # Exclude cancelled batches (docstatus != 2, status != 'Cancelled').
    # Completed batches: is_completed == 1 or status == 'Completed'.
    stage_batches = []
    for stg_num, stg_label in [(1, "Stage 1 – Insert Making"), (2, "Stage 2 – PU & Casting"), (3, "Stage 3 – CNC")]:
        dt = f"Stage {stg_num} Batch"
        filters = {
            "docstatus": ["!=", 2],
            "status": ["!=", "Cancelled"],
        }
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
                    "unit_cost", "rejection_percent", "rejection_amount", "rejected_qty",
                    "accepted_qty", "production_code", "remarks"
                ],
                order_by="posting_date asc",
                ignore_permissions=True,
            )
            for r in rows:
                if not (cint(r.get("is_completed")) == 1 or r.get("status") == "Completed"):
                    continue
                r["stage_num"] = stg_num
                r["stage_label"] = stg_label
                stage_batches.append(r)
        except Exception as exc:
            frappe.log_error(str(exc), f"get_monthly_production_report: {dt}")

    
    # 2b. Belt Batches Query
    if frappe.db.exists("DocType", "Belt Batch"):
        bb_filters = {"docstatus": ["!=", 2]}
        if from_str and to_str:
            bb_filters["posting_date"] = ["between", [from_str, to_str]]
        elif from_str:
            bb_filters["posting_date"] = [">=", from_str]
        elif to_str:
            bb_filters["posting_date"] = ["<=", to_str]

        try:
            bb_rows = frappe.get_all(
                "Belt Batch",
                filters=bb_filters,
                fields=[
                    "name", "product", "quantity", "posting_date", "process_step",
                    "stage", "is_completed", "unit_cost", "batch_total",
                    "remarks", "creation"
                ],
                order_by="posting_date asc",
                ignore_permissions=True,
            )
            for r in bb_rows:
                if not r.get("posting_date") and r.get("creation"):
                    r["posting_date"] = str(r["creation"])[:10]
                step = cint(r.get("process_step")) or cint("".join(filter(str.isdigit, str(r.get("stage") or ""))) or 1) or 1
                r["stage_num"] = step
                belt_labels = {
                    1: "Stage 1 – Roll Creation",
                    2: "Stage 2 – Roll Sizing",
                    3: "Stage 3 – Roll Finished",
                    4: "Stage 4 – Charges"
                }
                r["stage_label"] = belt_labels.get(step, f"Stage {step}")
                r["is_belt"] = True
                stage_batches.append(r)
        except Exception as exc:
            frappe.log_error(str(exc), "get_monthly_production_report: Belt Batch")

    # 3. Confirmed Dispatches in Date Range
    # Rules 3 & 4:
    # Partial dispatches must count only confirmed dispatched quantities.
    # Cancelled dispatches must not count.
    # d.dispatch_status == 'Dispatched' AND d.docstatus != 2
    dispatches_by_product = {}
    dispatch_details_by_product = {}
    try:
        tab_di = "`tabDispatch Item`"
        tab_d = "`tabDispatch`"
        d_conds = ["d.dispatch_status = 'Dispatched'", "d.docstatus != 2"]
        d_params = {}
        if from_str:
            d_conds.append("d.dispatch_date >= %(from_date)s")
            d_params["from_date"] = from_str
        if to_str:
            d_conds.append("d.dispatch_date <= %(to_date)s")
            d_params["to_date"] = to_str

        where_d = " AND ".join(d_conds)
        disp_sql = f"""
            SELECT
                di.product,
                di.quantity,
                d.name as dispatch_no,
                d.dispatch_date,
                d.customer,
                d.sales_order,
                di.unit_cost
            FROM {tab_di} di
            JOIN {tab_d} d ON d.name = di.parent
            WHERE {where_d}
            ORDER BY d.dispatch_date ASC
        """
        disp_rows = frappe.db.sql(disp_sql, d_params, as_dict=True)
        for dr in disp_rows:
            p_val = dr.get("product") or ""
            q = flt(dr.get("quantity") or 0)
            dispatches_by_product[p_val] = dispatches_by_product.get(p_val, 0.0) + q
            if p_val not in dispatch_details_by_product:
                dispatch_details_by_product[p_val] = []
            dispatch_details_by_product[p_val].append({
                "dispatch_no": dr.get("dispatch_no") or "",
                "dispatch_date": str(dr.get("dispatch_date") or ""),
                "customer": dr.get("customer") or "",
                "sales_order": dr.get("sales_order") or "",
                "quantity": q,
                "unit_cost": flt(dr.get("unit_cost") or 0),
            })
    except Exception as exc:
        frappe.log_error(str(exc), "get_monthly_production_report: Dispatches query")

    # 4. Confirmed Customer Returns in Date Range
    returns_by_product = {}
    return_details_by_product = {}
    try:
        tab_cri = "`tabCustomer Return Item`"
        tab_cr = "`tabCustomer Return`"
        r_conds = ["cr.return_status = 'Confirmed'", "cr.docstatus != 2"]
        r_params = {}
        if from_str:
            r_conds.append("cr.return_date >= %(from_date)s")
            r_params["from_date"] = from_str
        if to_str:
            r_conds.append("cr.return_date <= %(to_date)s")
            r_params["to_date"] = to_str

        where_r = " AND ".join(r_conds)
        ret_sql = f"""
            SELECT
                cri.product,
                cri.return_qty,
                cri.condition,
                cr.name as return_no,
                cr.return_date,
                cr.customer,
                cr.dispatch,
                cr.sales_order
            FROM {tab_cri} cri
            JOIN {tab_cr} cr ON cr.name = cri.parent
            WHERE {where_r}
            ORDER BY cr.return_date ASC
        """
        ret_rows = frappe.db.sql(ret_sql, r_params, as_dict=True)
        for rr in ret_rows:
            p_val = rr.get("product") or ""
            rq = flt(rr.get("return_qty") or 0)
            returns_by_product[p_val] = returns_by_product.get(p_val, 0.0) + rq
            if p_val not in return_details_by_product:
                return_details_by_product[p_val] = []
            return_details_by_product[p_val].append({
                "return_no": rr.get("return_no") or "",
                "return_date": str(rr.get("return_date") or ""),
                "customer": rr.get("customer") or "",
                "dispatch": rr.get("dispatch") or "",
                "sales_order": rr.get("sales_order") or "",
                "return_qty": rq,
                "condition": rr.get("condition") or "Usable",
            })
    except Exception as exc:
        frappe.log_error(str(exc), "get_monthly_production_report: Customer returns query")

    # 5. Current Available Inventory Stock
    # Rule 7: Keep current available inventory as a separate column.
    available_stock_by_product = {}
    inventory_breakdown_by_product = {}
    try:
        inv_rows = frappe.get_all(
            "Inventory",
            fields=["name", "product", "stage", "stock", "unit_price"],
            ignore_permissions=True,
        )
        for inv in inv_rows:
            p_val = inv.get("product") or ""
            stg = inv.get("stage") or ""
            stk = flt(inv.get("stock") or 0)
            if p_val not in inventory_breakdown_by_product:
                inventory_breakdown_by_product[p_val] = {}
            inventory_breakdown_by_product[p_val][stg] = stk

            if stg == "Finished":
                available_stock_by_product[p_val] = available_stock_by_product.get(p_val, 0.0) + stk
    except Exception as exc:
        frappe.log_error(str(exc), "get_monthly_production_report: Inventory query")

    # 6. Determine which products to show
    # Include any product that had production batches, confirmed dispatches, or customer returns in this period.
    # Handle products with zero available stock but non-zero historical production.
    candidate_products = set()
    for b in stage_batches:
        if b.get("product"):
            candidate_products.add(b.get("product"))
    for p_id in dispatches_by_product:
        candidate_products.add(p_id)
    for p_id in returns_by_product:
        candidate_products.add(p_id)

    # If filters provided, filter candidates
    filtered_p_ids = []
    for p_id in candidate_products:
        p_info = get_prod(p_id)
        p_code = p_info.get("product_code") or p_id
        prod_name = p_info.get("product_name") or p_id
        prod_c = p_info.get("production_code") or ""

        if product and (product.lower() not in p_id.lower() and product.lower() not in prod_name.lower()):
            continue
        if product_code and (product_code.lower() not in p_code.lower()):
            continue
        if production_code and (production_code.lower() not in prod_c.lower()):
            continue
        filtered_p_ids.append(p_id)

    # 7. Build product aggregated rows
    rows = []
    total_stage1_all = 0.0
    total_stage2_all = 0.0
    total_stage3_all = 0.0
    total_produced_all = 0.0
    total_dispatched_all = 0.0
    total_returned_all = 0.0
    total_stock_all = 0.0
    total_rejected_all = 0.0
    total_cost_all = 0.0

    for p_id in filtered_p_ids:
        p_info = get_prod(p_id)
        p_code = p_info.get("product_code") or p_id
        prod_name = p_info.get("product_name") or p_id
        uom = p_info.get("uom") or "PCS"
        total_steps = cint(p_info.get("total_steps") or 3)
        prod_c = p_info.get("production_code") or "—"

        p_batches = [b for b in stage_batches if b.get("product") == p_id]
        p_dispatches = dispatch_details_by_product.get(p_id, [])
        p_returns = return_details_by_product.get(p_id, [])

        stage1_qty = 0.0
        stage2_qty = 0.0
        stage3_qty = 0.0
        stage4_qty = 0.0
        rejected_qty = 0.0
        total_net_cost = 0.0
        latest_date = ""
        batch_details = []

        for b in p_batches:
            raw_date = str(b.get("posting_date") or "")[:10]
            if raw_date and (not latest_date or raw_date > latest_date):
                latest_date = raw_date

            if b.get("production_code") and (prod_c == "—" or not prod_c):
                prod_c = b.get("production_code")

            qty = flt(b.get("quantity") or 0)
            rej_pct = flt(b.get("rejection_percent") or 0)
            rej_amt = flt(b.get("rejected_qty") or 0)
            if rej_amt <= 0 and rej_pct > 0:
                rej_amt = round(qty * rej_pct / 100.0, 4)

            b_total = flt(b.get("batch_total") or 0)
            carried = flt(b.get("carried_cost") or 0)
            added = flt(b.get("added_cost") or 0)

            stg = b["stage_num"]
            if stg == 1:
                stage1_qty += qty
                net_cost = b_total if b_total > 0 else added
            elif stg == 2:
                stage2_qty += qty
                if carried > 0 and b_total >= carried:
                    net_cost = b_total - carried
                else:
                    net_cost = added if added > 0 else b_total
            elif stg == 4:
                stage4_qty += qty
                net_cost = b_total if b_total > 0 else added
            else:
                stage3_qty += qty
                if carried > 0 and b_total >= carried:
                    net_cost = b_total - carried
                else:
                    net_cost = added if added > 0 else b_total

            rejected_qty += rej_amt
            total_net_cost += net_cost

            batch_details.append({
                "production_date": raw_date,
                "batch_no": b.get("name") or "",
                "product_code": p_code,
                "production_code": b.get("production_code") or prod_c,
                "product_name": prod_name,
                "stage": b.get("stage_label") or f"Stage {stg}",
                "produced_qty": qty,
                "rejected_qty": rej_amt,
                "batch_status": b.get("status") or "Completed",
                "production_cost": b_total,
                "unit_cost": flt(b.get("unit_cost") or 0),
            })

        # Rule 8:
        # Do not add the three stage quantities together as total finished production
        # if they represent the same material moving through successive stages.
        # Calculate total finished production from the final completed production stage.
        is_belt_prod = any(b.get("is_belt") for b in p_batches)
        if is_belt_prod:
            total_produced = stage4_qty if stage4_qty > 0 else (stage3_qty if stage3_qty > 0 else (stage2_qty if stage2_qty > 0 else stage1_qty))
        elif total_steps == 1:
            total_produced = stage1_qty
        elif total_steps == 2:
            total_produced = stage2_qty
        else:
            total_produced = stage3_qty

        dispatched_qty = dispatches_by_product.get(p_id, 0.0)
        return_qty = returns_by_product.get(p_id, 0.0)

        # Available Stock: Finished stock in inventory (or final stage if no finished)
        avail_stock = available_stock_by_product.get(p_id, 0.0)
        if avail_stock == 0.0:
            final_stage_key = f"Stage {total_steps}"
            avail_stock = inventory_breakdown_by_product.get(p_id, {}).get(final_stage_key, 0.0)

        # Belt products: Inventory Page stores "Finished" stock in browser localStorage,
        # NOT in tabInventory DB. So compute belt available stock directly from Belt Batch data.
        # Available = highest stage batches qty - dispatched + returned
        if avail_stock == 0.0 and is_belt_prod and p_batches:
            # Find the maximum stage number that exists for this product
            belt_max_stage = max((b["stage_num"] for b in p_batches), default=0)
            belt_top_qty = sum(
                flt(b.get("quantity") or 0)
                for b in p_batches
                if b["stage_num"] == belt_max_stage
            )
            dispatched_for_avail = dispatches_by_product.get(p_id, 0.0)
            returned_for_avail = returns_by_product.get(p_id, 0.0)
            avail_stock = max(0.0, belt_top_qty - dispatched_for_avail + returned_for_avail)

        # Date for presentation
        if not latest_date:
            if p_dispatches:
                latest_date = p_dispatches[-1].get("dispatch_date", "")
            elif p_returns:
                latest_date = p_returns[-1].get("return_date", "")
            else:
                latest_date = to_str or from_str

        m_num = 1
        m_year = 2026
        month_name = "October 2026"
        if latest_date:
            try:
                d_obj = datetime.datetime.strptime(latest_date[:10], "%Y-%m-%d")
                m_num = d_obj.month
                m_year = d_obj.year
                month_name = d_obj.strftime("%B %Y")
            except Exception:
                pass

        total_stage1_all += stage1_qty
        total_stage2_all += stage2_qty
        total_stage3_all += stage3_qty
        total_produced_all += total_produced
        total_dispatched_all += dispatched_qty
        total_returned_all += return_qty
        total_stock_all += avail_stock
        total_rejected_all += rejected_qty
        total_cost_all += total_net_cost

        rows.append({
            "product": p_id,
            "product_code": p_code,
            "product_name": prod_name,
            "production_code": prod_c,
            "uom": uom,
            "total_steps": total_steps,
            "production_date": latest_date,
            "month_no": m_num,
            "month": month_name,
            "year": m_year,
            "stage1_qty": round(stage1_qty, 2),
            "stage2_qty": round(stage2_qty, 2),
            "stage3_qty": round(stage3_qty, 3),
            "stage4_qty": round(stage4_qty, 3),
            "is_belt": is_belt_prod,
            "total_produced_qty": round(total_produced, 2),
            "finished_goods_qty": round(total_produced, 3),
            "dispatched_qty": round(dispatched_qty, 3),
            "total_dispatched_qty": round(dispatched_qty, 3),
            "return_qty": round(return_qty, 3),
            "customer_return_qty": round(return_qty, 3),
            "available_stock": round(avail_stock, 3),
            "rejected_qty": round(rejected_qty, 3),
            "total_production_cost": round(total_net_cost, 2),
            "batches": batch_details,
            "dispatches": p_dispatches,
            "returns": p_returns,
            "inventory_breakdown": inventory_breakdown_by_product.get(p_id, {}),
        })

    rows.sort(key=lambda x: (x["production_date"], x["product_name"]), reverse=True)
    return {
        "success": True,
        "from_date": from_str,
        "to_date": to_str,
        "rows": rows,
        "total_count": len(rows),
        "summary": {
            "stage1_total": round(total_stage1_all, 2),
            "stage2_total": round(total_stage2_all, 2),
            "stage3_total": round(total_stage3_all, 3),
            "stage4_total": round(sum(r.get("stage4_qty", 0) for r in rows), 3),
            "total_produced": round(total_produced_all, 2),
            "total_dispatched": round(total_dispatched_all, 2),
            "total_returned": round(total_returned_all, 2),
            "total_available_stock": round(total_stock_all, 3),
            "total_rejected": round(total_rejected_all, 2),
            "total_production_cost": round(total_cost_all, 2),
        },
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
        conds.append("operation LIKE %(process)s")
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
            operation,
            operation AS process,
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
        "summary": summary_rows,
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
            operation, operator, start_time, end_time, total_duration_mins, running_time_mins,
            downtime_mins, qty_processed, accepted_qty, rejected_qty, remarks
        FROM `tabCNC Machine Log`
        {where_sql}
        ORDER BY production_date DESC, start_time DESC
    """, params, as_dict=True)

    for l in logs:
        m_type = frappe.db.get_value("CNC Machine", l.machine, "machine_type") or l.operation or ""
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
                    m_type = frappe.db.get_value("CNC Machine", b.machine, "machine_type") or b.get("operation") or b.get("process") or ""

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
def move_to_finished(
    product,
    qty,
    batch_no=None,
    production_code=None,
    destination_location="Finished Goods Warehouse",
    remarks=None,
    from_stage=None,
):
    """
    Section 6: Stage-Based Move to Finished Goods
    Enforces product's configured stages:
      - 1-Stage product: only Stage 1 can transfer.
      - 2-Stage product: only Stage 2 can transfer (Stage 1 prohibited).
      - 3-Stage product: only Stage 3 can transfer (Stage 1 & 2 prohibited).
      - 4-Stage product (Belt): only Stage 4 can transfer.
    Validates stage compliance, verifies available stock, row-locks,
    and moves stock atomically using stock_service.post.
    """
    from clssurya.utils.stock_service import _locked_row, post, inventory_price

    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Transfer quantity must be greater than zero."))

    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & {"CS Admin", "System Manager", "CS Production", "CS Store", "Administrator"}):
        raise frappe.PermissionError(_("You do not have permission to transfer stock to Finished Goods."))

    # 1. Fetch product configuration
    prod = frappe.db.sql("""
        SELECT name, product_name, product_code, product_type, finished_good_type, category, total_steps, production_code
        FROM `tabProduct`
        WHERE name = %s OR product_code = %s
        LIMIT 1
    """, (product, product), as_dict=True)

    if not prod:
        frappe.throw(_("Product '{0}' not found.").format(product))

    p = prod[0]
    prod_name = p.name
    is_belt = (p.finished_good_type == "Belt" or (p.category or "").lower() == "belt" or "BELT" in str(prod_name).upper())
    total_steps = int(p.total_steps or 0)
    if not total_steps:
        total_steps = 4 if is_belt else 3

    expected_final_stage = f"Stage {total_steps}"

    # 2. Stage verification
    if from_stage:
        norm_from = str(from_stage).strip()
        if norm_from.isdigit():
            norm_from = f"Stage {norm_from}"
        elif "stage" in norm_from.lower():
            digits = "".join(filter(str.isdigit, norm_from))
            if digits:
                norm_from = f"Stage {digits}"

        if norm_from != expected_final_stage:
            frappe.throw(
                _("Product '{0}' is configured for {1} production stages. "
                  "Transfer to Finished Goods is only allowed from its final stage ({2}), but attempted from '{3}'.").format(
                      p.product_name or prod_name, total_steps, expected_final_stage, from_stage
                  ),
                title=_("Invalid Production Stage")
            )

    source_stage = expected_final_stage

    # 3. Concurrency-safe row locking on the source stage
    row = _locked_row(prod_name, source_stage)
    available_stock = flt(row.stock)

    # For Belt products: sync completed top-stage Belt Batches into tabInventory if needed
    if qty > available_stock + 1e-6 and is_belt and frappe.db.exists("DocType", "Belt Batch"):
        b_rows = frappe.db.sql("""
            SELECT name, quantity, unit_cost, batch_total, process_step
            FROM `tabBelt Batch`
            WHERE product = %s AND is_completed = 1 AND docstatus != 2
            ORDER BY process_step DESC
        """, (prod_name,), as_dict=True)
        if b_rows:
            max_step = max(int(b["process_step"]) for b in b_rows)
            if max_step == total_steps:
                top_batches = [b for b in b_rows if int(b["process_step"]) == max_step]
                total_top_qty = sum(flt(b["quantity"]) for b in top_batches)
                posted_qty = flt((frappe.db.sql("""
                    SELECT SUM(qty_in) FROM `tabStock Ledger Entry`
                    WHERE product=%s AND stage=%s AND reference_doctype='Belt Batch'
                """, (prod_name, source_stage)) or [[0]])[0][0] or 0)
                if total_top_qty > posted_qty + 1e-6:
                    for b in top_batches:
                        u_cost = flt(b.get("unit_cost") or 0)
                        post([{"product": prod_name, "stage": source_stage, "qty": flt(b["quantity"]), "unit_price": u_cost}], "Belt Batch", b["name"])
                    row = _locked_row(prod_name, source_stage)
                    available_stock = flt(row.stock)

    if qty > available_stock + 1e-6:
        frappe.throw(
            _("Requested transfer quantity ({0}) exceeds available {1} quantity ({2}).").format(
                qty, source_stage, available_stock
            ),
            title=_("Insufficient Stage Stock")
        )

    unit_cost = flt(row.unit_price) if available_stock > 1e-6 else inventory_price(prod_name, source_stage)

    # If production_code is provided, persist it to Product
    if production_code and frappe.db.has_column("Product", "production_code"):
        frappe.db.set_value("Product", prod_name, "production_code", production_code, update_modified=False)
    elif not production_code:
        production_code = p.production_code or ""

    ref_dt = "Inventory"
    if batch_no:
        if is_belt and frappe.db.exists("Belt Batch", batch_no):
            ref_dt = "Belt Batch"
        elif total_steps == 1 and frappe.db.exists("Stage 1 Batch", batch_no):
            ref_dt = "Stage 1 Batch"
        elif total_steps == 2 and frappe.db.exists("Stage 2 Batch", batch_no):
            ref_dt = "Stage 2 Batch"
        elif total_steps == 3 and frappe.db.exists("Stage 3 Batch", batch_no):
            ref_dt = "Stage 3 Batch"

    ref_name = batch_no or f"M2F-{prod_name}-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"

    entries = [
        {"product": prod_name, "stage": source_stage, "qty": -qty},
        {"product": prod_name, "stage": "Finished", "qty": qty, "unit_price": unit_cost},
    ]

    post(entries, ref_dt, ref_name)

    return {
        "success": True,
        "product": prod_name,
        "batch_no": batch_no,
        "from_stage": source_stage,
        "production_code": production_code,
        "transferred_qty": qty,
        "remaining_source_stock": max(0.0, round(available_stock - qty, 4)),
        "unit_cost": unit_cost,
        "message": _("Successfully transferred {0} units of {1} from {2} to Finished Goods.").format(qty, p.product_name or prod_name, source_stage),
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
        {"doctype": "Belt Batch", "stage": "Stage 1", "label": "Stage 1 · Roll Creation", "step": 1},
        {"doctype": "Belt Batch", "stage": "Stage 2", "label": "Stage 2 · Roll Sizing", "step": 2},
        {"doctype": "Belt Batch", "stage": "Stage 3", "label": "Stage 3 · Roll Finished", "step": 3},
        {"doctype": "Belt Batch", "stage": "Stage 4", "label": "Stage 4 · Charges", "step": 4},
    ]

    all_records = []
    prod_cache = {}

    for cfg in stage_configs:
        dt = cfg["doctype"]
        if not frappe.db.exists("DocType", dt):
            continue
        if stage and stage != "All" and stage not in (cfg["stage"], cfg["label"]):
            continue

        conds = ["COALESCE(posting_date, DATE(creation)) >= %(from_date)s AND COALESCE(posting_date, DATE(creation)) <= %(to_date)s"]
        if dt == "Belt Batch" and cfg.get("step"):
            conds.append("(process_step = " + str(cfg["step"]) + " OR stage = 'Stage " + str(cfg["step"]) + "')")
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


@frappe.whitelist()
def get_pending_order_analysis(from_date=None, to_date=None, vendor=None, product=None, include_completed=0):
    """
    Pending Order Analysis Report:
    Compares ordered quantities in Purchase Entry records against actual received quantities from confirmed Goods Receipts.
    Hides fully received items by default (include_completed=0).
    Dual independent filters: Vendor Wise, Product Wise, plus optional Date Range.
    """
    # 1. Fetch confirmed goods receipt quantities per purchase order item row
    gr_receipts = frappe.db.sql("""
        SELECT 
            gri.purchase_order_item,
            SUM(gri.received_qty) as total_received
        FROM `tabGoods Receipt Item` gri
        JOIN `tabGoods Receipt` gr ON gr.name = gri.parent
        WHERE gr.status = 'Confirmed' AND gr.docstatus != 2
        GROUP BY gri.purchase_order_item
    """, as_dict=True)
    rcv_map = {r.purchase_order_item: flt(r.total_received) for r in gr_receipts}

    conditions = ["pe.status != 'Cancelled'", "pe.docstatus != 2"]
    values = {}

    if from_date:
        conditions.append("pe.posting_date >= %(from_date)s")
        values["from_date"] = from_date
    if to_date:
        conditions.append("pe.posting_date <= %(to_date)s")
        values["to_date"] = to_date
    if vendor and str(vendor).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("pe.vendor = %(vendor)s")
        values["vendor"] = vendor
    if product and str(product).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("pei.product = %(product)s")
        values["product"] = product

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT 
            pe.name as purchase_entry_id,
            pe.posting_date as purchase_date,
            pe.vendor,
            v.vendor_name,
            pe.status as order_status,
            pei.name as item_row_name,
            pei.product as product_code,
            p.product_name,
            pei.uom,
            pei.quantity as ordered_qty,
            pei.received_qty as pei_received_qty,
            pei.pending_qty as pei_pending_qty,
            pei.rate as unit_rate,
            pei.landed_rate
        FROM `tabPurchase Entry` pe
        JOIN `tabPurchase Entry Item` pei ON pei.parent = pe.name
        LEFT JOIN `tabVendor` v ON v.name = pe.vendor
        LEFT JOIN `tabProduct` p ON p.name = pei.product
        WHERE {where_clause}
        ORDER BY pe.posting_date DESC, pe.name DESC
    """
    raw_rows = frappe.db.sql(query, values, as_dict=True)

    rows = []
    tot_ordered = 0.0
    tot_received = 0.0
    tot_pending = 0.0
    tot_pending_val = 0.0

    inc_comp = 1 if include_completed in ("1", 1, "true", "True", True) else 0

    for r in raw_rows:
        ordered = flt(r.ordered_qty)
        actual_rcv = rcv_map.get(r.item_row_name, flt(r.pei_received_qty))
        pending = max(0.0, ordered - actual_rcv)

        if not inc_comp and pending <= 0.000001:
            continue

        unit_rate = flt(r.unit_rate)
        landed_rate = flt(r.landed_rate) if flt(r.landed_rate) else unit_rate
        pending_val = round(pending * unit_rate, 2)

        vendor_display = r.vendor_name or r.vendor or "Unknown Vendor"
        prod_display = r.product_name or r.product_code or ""

        rows.append({
            "purchase_entry_id": r.purchase_entry_id,
            "purchase_date": str(r.purchase_date) if r.purchase_date else "",
            "vendor_name": vendor_display,
            "vendor_id": r.vendor,
            "product_code": r.product_code,
            "product_name": prod_display,
            "uom": r.uom or "",
            "ordered_qty": ordered,
            "received_qty": actual_rcv,
            "pending_qty": pending,
            "unit_rate": unit_rate,
            "landed_rate": landed_rate,
            "order_status": r.order_status or "Draft",
            "pending_value": pending_val,
        })

        tot_ordered += ordered
        tot_received += actual_rcv
        tot_pending += pending
        tot_pending_val += pending_val

    # Vendors & products for filters
    vendor_list = frappe.db.sql("SELECT name, vendor_name FROM `tabVendor` ORDER BY vendor_name ASC", as_dict=True)
    product_list = frappe.db.sql("SELECT name, product_name FROM `tabProduct` ORDER BY product_name ASC", as_dict=True)

    vendors = [{"value": "ALL", "label": "All Vendors"}] + [
        {"value": v.name, "label": v.vendor_name or v.name} for v in vendor_list
    ]
    products = [{"value": "ALL", "label": "All Products"}] + [
        {"value": p.name, "label": f"{p.name} - {p.product_name}" if p.product_name else p.name} for p in product_list
    ]

    return {
        "rows": rows,
        "summary": {
            "total_ordered_qty": round(tot_ordered, 4),
            "total_received_qty": round(tot_received, 4),
            "total_pending_qty": round(tot_pending, 4),
            "total_pending_value": round(tot_pending_val, 2),
            "total_rows": len(rows),
        },
        "vendors": vendors,
        "products": products,
    }


# ============================================================================
# USER MANAGEMENT & SALES PERSON DASHBOARD APIS
# ============================================================================

@frappe.whitelist()
def get_sales_person_dashboard():
    """Returns dashboard metrics for the logged-in Sales Person or filtered scope."""
    user = frappe.session.user
    sp = get_current_sales_person(user)
    admin = is_admin(user)

    sp_filter = {}
    if not admin and sp:
        sp_filter["sales_person"] = sp.name
    elif not admin and not sp:
        return {
            "total_customers": 0,
            "total_quotations": 0,
            "pending_quotations": 0,
            "accepted_quotations": 0,
            "total_sales_orders": 0,
            "pending_orders": 0,
            "completed_orders": 0,
            "monthly_sales_amount": 0,
            "recent_quotations": [],
            "recent_orders": [],
            "monthly_chart": [],
            "pending_approvals": [],
        }

    # Customers
    cust_filter = sp_filter.copy()
    total_customers = frappe.db.count("Customer", cust_filter) if cust_filter else frappe.db.count("Customer")

    # Quotations
    q_all = frappe.get_all(
        "Quotation",
        filters=sp_filter,
        fields=["name", "customer", "quotation_date", "grand_total", "status", "version"],
        order_by="quotation_date desc, creation desc",
        limit=50,
    )
    total_quotations = len(q_all)
    pending_quotations = sum(1 for q in q_all if q.get("status") in ("Draft", "Sent", "Pending Approval"))
    accepted_quotations = sum(1 for q in q_all if q.get("status") in ("Accepted", "Approved"))

    # Sales Orders
    so_all = frappe.get_all(
        "Sales Order",
        filters=sp_filter,
        fields=["name", "customer", "order_date", "grand_total", "status", "quotation"],
        order_by="order_date desc, creation desc",
        limit=50,
    )
    total_sales_orders = len(so_all)
    pending_orders = sum(1 for o in so_all if o.get("status") in ("Draft", "Pending Approval"))
    completed_orders = sum(1 for o in so_all if o.get("status") in ("Completed", "Partially Dispatched"))

    # Monthly sales: Current month orders
    from frappe.utils import nowdate, getdate
    cur_month = str(nowdate())[:7]
    monthly_sales_amount = sum(
        flt(o.get("grand_total") or 0) for o in so_all if str(o.get("order_date") or "")[:7] == cur_month
    )

    # Monthly chart data (last 6 months)
    monthly_chart = []
    import datetime
    today = getdate(nowdate())
    for i in range(5, -1, -1):
        d = today - datetime.timedelta(days=i * 30)
        m_str = d.strftime("%Y-%m")
        m_label = d.strftime("%b %y")
        m_quotes = sum(flt(q.get("grand_total") or 0) for q in q_all if str(q.get("quotation_date") or "")[:7] == m_str)
        m_orders = sum(flt(o.get("grand_total") or 0) for o in so_all if str(o.get("order_date") or "")[:7] == m_str)
        monthly_chart.append({
            "month": m_label,
            "quotations_amount": m_quotes,
            "orders_amount": m_orders,
        })

    # Pending approvals queue
    pending_approvals = []
    for q in q_all:
        if q.get("status") in ("Draft", "Sent", "Pending Approval"):
            pending_approvals.append({
                "type": "Quotation",
                "name": q.name,
                "customer": q.customer,
                "date": q.quotation_date,
                "amount": flt(q.grand_total or 0),
                "status": q.status or "Draft",
            })
    for o in so_all:
        if o.get("status") in ("Pending Approval", "Draft"):
            pending_approvals.append({
                "type": "Sales Order",
                "name": o.name,
                "customer": o.customer,
                "date": o.order_date,
                "amount": flt(o.grand_total or 0),
                "status": o.status or "Draft",
            })

    return {
        "total_customers": total_customers,
        "total_quotations": total_quotations,
        "pending_quotations": pending_quotations,
        "accepted_quotations": accepted_quotations,
        "total_sales_orders": total_sales_orders,
        "pending_orders": pending_orders,
        "completed_orders": completed_orders,
        "monthly_sales_amount": monthly_sales_amount,
        "recent_quotations": q_all[:5],
        "recent_orders": so_all[:5],
        "monthly_chart": monthly_chart,
        "pending_approvals": pending_approvals[:10],
    }


@frappe.whitelist()
def get_user_management_list():
    """Administrator-only: fetches all users, their roles, and linked Sales Person records."""
    require_admin()
    users = frappe.get_all(
        "User",
        filters={"name": ["not in", ["Guest"]]},
        fields=["name", "email", "first_name", "last_name", "full_name", "enabled", "creation", "last_login"],
        order_by="creation desc",
    )

    # Fetch all sales persons
    sp_list = frappe.get_all(
        "Sales Person",
        fields=["name", "sales_person_name", "employee_id", "email", "assigned_user", "status", "mobile_no"],
    )
    sp_by_user = {sp.assigned_user: sp for sp in sp_list if sp.assigned_user}
    sp_by_email = {sp.email: sp for sp in sp_list if sp.email}

    result = []
    for u in users:
        roles = frappe.get_roles(u.name)
        sp = sp_by_user.get(u.name) or sp_by_email.get(u.email)
        is_sp = "Sales Person" in roles or "CS Sales" in roles
        is_adm = u.name == "Administrator" or "System Manager" in roles or "CS Admin" in roles
        result.append({
            "name": u.name,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "full_name": u.full_name or u.first_name or u.email,
            "enabled": cint(u.enabled),
            "roles": roles,
            "is_admin": is_adm,
            "is_sales_person": is_sp,
            "sales_person_name": sp.get("sales_person_name") if sp else None,
            "sales_person_id": sp.get("name") if sp else None,
            "sales_person_status": sp.get("status") if sp else None,
            "employee_id": sp.get("employee_id") if sp else None,
            "mobile_no": sp.get("mobile_no") if sp else None,
        })

    return result


@frappe.whitelist()
def create_user_and_sales_person(email, first_name, password=None, role="Sales Person", last_name=None, employee_id=None, mobile_no=None, address=None):
    """Administrator-only: creates user, sets password, assigns role, and creates or links Sales Person record."""
    require_admin()
    if not email or not first_name:
        frappe.throw(_("Email and first name are required."))

    email = email.strip().lower()
    first_name = first_name.strip()
    last_name = (last_name or "").strip()

    if not frappe.db.exists("User", email) and not password:
        frappe.throw(_("Password is required for new users."))

    # Create or update Frappe User
    if frappe.db.exists("User", email):
        user_doc = frappe.get_doc("User", email)
        user_doc.enabled = 1
        user_doc.first_name = first_name
        if last_name:
            user_doc.last_name = last_name
        user_doc.save(ignore_permissions=True)
    else:
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "send_welcome_email": 0,
            "enabled": 1,
        })
        user_doc.insert(ignore_permissions=True)

    # Set password securely if provided
    if password:
        from frappe.utils.password import update_password
        update_password(email, password)

    # Ensure roles exist in Frappe
    for r_name in ["Store Executive", "PU Operator", "Belt Operator", "Sales Person", "CS Admin", "CS Store", "CS Production", "CS Sales"]:
        if not frappe.db.exists("Role", r_name):
            try:
                frappe.get_doc({"doctype": "Role", "role_name": r_name, "desk_access": 1}).insert(ignore_permissions=True)
            except Exception:
                pass

    # Remove conflicting roles before re-assigning (keep Administrator superuser untouched)
    if email not in ("administrator", "Administrator"):
        try:
            user_doc.remove_roles(
                "Store Executive", "PU Operator", "Belt Operator",
                "Sales Person", "CS Sales", "CS Admin", "System Manager",
                "CS Store", "CS Production"
            )
        except Exception:
            pass

    # Assign roles
    if role == "Administrator":
        user_doc.add_roles("System Manager", "CS Admin")
    elif role == "Store Executive":
        user_doc.add_roles("Store Executive", "CS Store")
    elif role == "PU Operator":
        user_doc.add_roles("PU Operator", "CS Production")
    elif role == "Belt Operator":
        user_doc.add_roles("Belt Operator", "CS Production")
    else:
        user_doc.add_roles("Sales Person", "CS Sales")

    # If Sales Person, create or link Sales Person record
    if role == "Sales Person":
        sp_name = f"{first_name} {last_name}".strip() if last_name else first_name
        if sp_name.strip().lower() == "sales person":
            sp_name = f"{sp_name} 1" 

        # Check if Sales Person already exists by assigned_user, email, name, or employee_id
        existing_sp = (
            frappe.db.get_value("Sales Person", {"assigned_user": email}, "name")
            or frappe.db.get_value("Sales Person", {"email": email}, "name")
            or frappe.db.get_value("Sales Person", {"sales_person_name": sp_name}, "name")
            or (frappe.db.get_value("Sales Person", {"employee_id": employee_id}, "name") if employee_id else None)
        )

        if existing_sp:
            sp_doc = frappe.get_doc("Sales Person", existing_sp)
            sp_doc.assigned_user = email
            sp_doc.email = email
            sp_doc.status = "Active"
            if mobile_no:
                sp_doc.mobile_no = mobile_no
            if address:
                sp_doc.address = address
            if employee_id:
                sp_doc.employee_id = employee_id
            sp_doc.save(ignore_permissions=True)
        else:
            emp_id = employee_id or f"EMP-{frappe.generate_hash(length=4).upper()}"
            sp_doc = frappe.get_doc({
                "doctype": "Sales Person",
                "sales_person_name": sp_name,
                "employee_id": emp_id,
                "email": email,
                "mobile_no": mobile_no or "",
                "address": address or "",
                "assigned_user": email,
                "status": "Active",
                "joining_date": nowdate(),
            })
            sp_doc.insert(ignore_permissions=True)

    frappe.db.commit()
    return {"message": f"User {email} and Sales Person profile set up successfully"}

@frappe.whitelist()
def update_user_status(user, enabled):
    """Administrator-only: enable or disable a user and sync Sales Person status."""
    require_admin()
    if user == "Administrator":
        frappe.throw(_("Cannot disable Administrator account."))

    val = cint(enabled)
    frappe.db.set_value("User", user, "enabled", val)

    # If linked to a Sales Person, update Sales Person status
    sp_name = frappe.db.get_value("Sales Person", {"assigned_user": user}, "name")
    if sp_name:
        frappe.db.set_value("Sales Person", sp_name, "status", "Active" if val else "Inactive")

    return {"message": f"User status updated to {'Active' if val else 'Inactive'}"}


@frappe.whitelist()
def reset_user_password(user, new_password):
    """Administrator-only: resets a user's password securely."""
    require_admin()
    if not user or not new_password:
        frappe.throw(_("User and new password are required."))

    from frappe.utils.password import update_password
    update_password(user, new_password)
    return {"message": f"Password for {user} updated successfully"}


@frappe.whitelist()
def delete_user_and_sales_person(user):
    """Administrator-only: deletes a user and any linked Sales Person record."""
    require_admin()
    if user in ("Administrator", "surya@gmail.com"):
        frappe.throw(_("Cannot delete main Administrator accounts."))

    # Delete linked Sales Person
    sp_name = frappe.db.get_value("Sales Person", {"assigned_user": user}, "name")
    if not sp_name:
        sp_name = frappe.db.get_value("Sales Person", {"email": user}, "name")
    if sp_name:
        frappe.delete_doc("Sales Person", sp_name, ignore_permissions=True)

    # Delete Frappe User
    if frappe.db.exists("User", user):
        frappe.delete_doc("User", user, ignore_permissions=True)

    return {"message": f"User {user} and linked Sales Person deleted successfully"}

@frappe.whitelist()
def get_belt_production_report(from_date=None, to_date=None, product=None):
    """
    Comprehensive Belt Production Report API:
    1. Date-wise Production
    2. Product-wise Production
    3. Material Consumption (from Belt Batch Item child table)
    4. Roll Consumption (Roll Created, Required, Consumed, Wastage, Balance)
    5. Rejection & Wastage
    6. Manufacturing Cost & Charges
    """
    import datetime

    # 1. Filters
    conditions = ["docstatus != 2"]
    params = {}
    if from_date:
        conditions.append("posting_date >= %(from_date)s")
        params["from_date"] = str(from_date).strip()[:10]
    if to_date:
        conditions.append("posting_date <= %(to_date)s")
        params["to_date"] = str(to_date).strip()[:10]
    if product:
        conditions.append("(product LIKE %(product)s OR product = %(product_exact)s)")
        params["product"] = f"%{product.strip()}%"
        params["product_exact"] = product.strip()

    where_clause = " AND ".join(conditions)

    # 2. Query Belt Batches
    batches_sql = f"""
        SELECT 
            name, stage, process_step, current_process, product, belt_type, 
            quantity, posting_date, creation, size, length, width, holes, 
            roll_division_factor, roll_required, roll_consumed, remaining_roll, 
            wastage_qty, rejection_percent, rejection_amount, 
            carried_cost, added_cost, charge_total, batch_total, unit_cost, 
            is_completed, remarks
        FROM `tabBelt Batch`
        WHERE {where_clause}
        ORDER BY posting_date DESC, name DESC
    """
    batches = frappe.db.sql(batches_sql, params, as_dict=True)

    if not batches:
        return {
            "success": True,
            "from_date": from_date or "",
            "to_date": to_date or "",
            "batches": [],
            "product_summary": [],
            "date_summary": [],
            "material_consumption": [],
            "roll_consumption": {
                "summary": {
                    "total_roll_produced": 0.0,
                    "total_roll_consumed": 0.0,
                    "total_roll_required": 0.0,
                    "total_roll_wastage": 0.0,
                    "available_roll_balance": 0.0,
                },
                "batches": []
            },
            "rejection_summary": {
                "total_planned": 0.0,
                "total_produced": 0.0,
                "total_accepted": 0.0,
                "total_rejected": 0.0,
                "rejection_rate": 0.0,
                "total_wastage_qty": 0.0,
                "total_rejection_cost": 0.0,
                "batches": []
            },
            "cost_summary": {
                "total_carried_cost": 0.0,
                "total_added_cost": 0.0,
                "total_charges": 0.0,
                "total_cost": 0.0,
                "avg_unit_cost": 0.0,
                "batches": []
            },
            "summary": {
                "total_batches": 0,
                "total_planned": 0.0,
                "total_produced": 0.0,
                "total_accepted": 0.0,
                "total_roll_consumed": 0.0,
                "total_rejected": 0.0,
                "total_cost": 0.0,
                "avg_unit_cost": 0.0
            }
        }

    batch_names = [b["name"] for b in batches]

    # 3. Query Child Tables (Items & Charges)
    items_by_parent = {}
    charges_by_parent = {}
    if batch_names:
        placeholders = ", ".join(["%s"] * len(batch_names))
        items_sql = f"""
            SELECT parent, product, actual_utilization, unit_price, actual_amount, 
                   calculation_type, is_carried_in, idx
            FROM `tabBelt Batch Item`
            WHERE parent IN ({placeholders})
            ORDER BY parent, idx
        """
        raw_items = frappe.db.sql(items_sql, batch_names, as_dict=True)
        for it in raw_items:
            p = it["parent"]
            if p not in items_by_parent:
                items_by_parent[p] = []
            items_by_parent[p].append(it)

        charges_sql = f"""
            SELECT parent, charge, quantity, per_unit_price, amount, idx
            FROM `tabBelt Batch Charge`
            WHERE parent IN ({placeholders})
            ORDER BY parent, idx
        """
        raw_charges = frappe.db.sql(charges_sql, batch_names, as_dict=True)
        for ch in raw_charges:
            p = ch["parent"]
            if p not in charges_by_parent:
                charges_by_parent[p] = []
            charges_by_parent[p].append(ch)

    # 4. Process Each Batch with normalized fields
    stage_labels = {
        1: "Stage 1: Roll Creation",
        2: "Stage 2: Belt Sizing",
        3: "Stage 3: Belt Finishing",
        4: "Stage 4: Charges"
    }

    processed_batches = []
    material_map = {}
    product_agg = {}
    date_agg = {}

    total_roll_produced = 0.0
    total_roll_consumed = 0.0
    total_roll_required = 0.0
    total_roll_wastage = 0.0

    total_planned_all = 0.0
    total_produced_all = 0.0
    total_accepted_all = 0.0
    total_rejected_all = 0.0
    total_wastage_all = 0.0
    total_rejection_cost_all = 0.0

    total_carried_all = 0.0
    total_added_all = 0.0
    total_charges_all = 0.0
    total_cost_all = 0.0

    for b in batches:
        b_name = b["name"]
        b_items = items_by_parent.get(b_name, [])
        b_charges = charges_by_parent.get(b_name, [])

        p_date = str(b.get("posting_date") or str(b.get("creation") or "")[:10] or "")
        stg_num = cint(b.get("process_step") or b.get("stage") or 1)
        stg_name = b.get("current_process") or stage_labels.get(stg_num, f"Stage {stg_num}")
        p_name = b.get("product") or ""
        b_type = b.get("belt_type") or "Standard"

        qty = flt(b.get("quantity") or 0.0)
        length = flt(b.get("length") or 0.0)
        width = flt(b.get("width") or 0.0)
        holes = flt(b.get("holes") or 0.0)

        # Division Factor
        factor = flt(b.get("roll_division_factor") or 0.0)
        if factor <= 0 and width > 0:
            factor = 3.0 if width <= 100 else (2.0 if width <= 150 else 1.0)
        elif factor <= 0:
            factor = 1.0

        # Roll Required
        roll_req = flt(b.get("roll_required") or 0.0)
        if roll_req <= 0 and length > 0 and qty > 0 and factor > 0:
            roll_req = round((length / 1000.0 * qty) / factor, 3)

        # Roll Consumed
        roll_cons = flt(b.get("roll_consumed") or 0.0)
        if roll_cons <= 0:
            for it in b_items:
                it_prod = (it.get("product") or "").upper()
                if "ROLL" in it_prod or "FABRIC" in it_prod:
                    roll_cons = flt(it.get("actual_utilization") or 0.0)
                    break
        if roll_cons <= 0 and roll_req > 0:
            roll_cons = roll_req

        # Roll Wastage & Remaining
        roll_waste = max(0.0, round(roll_cons - roll_req, 3)) if (roll_cons > roll_req and roll_req > 0) else 0.0
        remaining_roll = flt(b.get("remaining_roll") or 0.0)

        # Rejection & Wastage
        wastage_q = flt(b.get("wastage_qty") or 0.0)
        rej_pct = flt(b.get("rejection_percent") or 0.0)
        rej_amt = flt(b.get("rejection_amount") or 0.0)
        rej_q = wastage_q if wastage_q > 0 else (round(qty * rej_pct / 100.0, 3) if rej_pct > 0 else 0.0)
        acc_q = max(0.0, round(qty - rej_q, 3))

        # Financials
        carried_c = flt(b.get("carried_cost") or 0.0)
        added_c = flt(b.get("added_cost") or 0.0)
        charge_tot = flt(b.get("charge_total") or 0.0)
        batch_tot = flt(b.get("batch_total") or 0.0)
        u_cost = flt(b.get("unit_cost") or (batch_tot / acc_q if acc_q > 0 else 0.0))

        # Track Roll Produced vs Consumed
        if stg_num == 1:
            total_roll_produced += qty
        elif stg_num == 2:
            total_roll_consumed += roll_cons
            total_roll_required += roll_req
            total_roll_wastage += roll_waste

        # Overall KPI accumulation
        total_planned_all += qty
        total_produced_all += qty
        total_accepted_all += acc_q
        total_rejected_all += rej_q
        total_wastage_all += wastage_q
        total_rejection_cost_all += rej_amt

        total_carried_all += carried_c
        total_added_all += added_c
        total_charges_all += charge_tot
        total_cost_all += batch_tot

        # Format items for this batch
        clean_items = []
        for it in b_items:
            m_code = it.get("product") or ""
            u_qty = flt(it.get("actual_utilization") or 0.0)
            u_rate = flt(it.get("unit_price") or 0.0)
            u_amt = flt(it.get("actual_amount") or (u_qty * u_rate))
            is_car = cint(it.get("is_carried_in") or 0)
            calc_t = it.get("calculation_type") or "Quantity"

            clean_items.append({
                "product": m_code,
                "utilization": round(u_qty, 3),
                "unit_price": round(u_rate, 2),
                "amount": round(u_amt, 2),
                "calculation_type": calc_t,
                "is_carried_in": is_car
            })

            # Material consumption aggregation
            is_inter = (m_code == p_name) or ("BELT" in m_code and "ROLL" not in m_code and stg_num > 1)
            if m_code not in material_map:
                material_map[m_code] = {
                    "product": m_code,
                    "total_consumed": 0.0,
                    "total_cost": 0.0,
                    "batches_used": [],
                    "is_intermediate": is_inter
                }
            material_map[m_code]["total_consumed"] += u_qty
            material_map[m_code]["total_cost"] += u_amt
            if b_name not in material_map[m_code]["batches_used"]:
                material_map[m_code]["batches_used"].append(b_name)

        # Batch object
        b_dict = {
            "name": b_name,
            "posting_date": p_date,
            "product": p_name,
            "belt_type": b_type,
            "stage": stg_num,
            "stage_name": stg_name,
            "status": "Completed" if cint(b.get("is_completed")) == 1 else "In Progress",
            "is_completed": cint(b.get("is_completed") or 0),
            "planned_quantity": round(qty, 3),
            "produced_quantity": round(qty, 3),
            "accepted_quantity": round(acc_q, 3),
            "rejected_quantity": round(rej_q, 3),
            "rejection_percent": round(rej_pct, 2),
            "wastage_qty": round(wastage_q, 3),
            "rejection_amount": round(rej_amt, 2),
            "length": round(length, 1),
            "width": round(width, 1),
            "holes": round(holes, 0),
            "roll_division_factor": round(factor, 1),
            "roll_required": round(roll_req, 3),
            "roll_consumed": round(roll_cons, 3),
            "roll_wastage": round(roll_waste, 3),
            "remaining_roll": round(remaining_roll, 3),
            "carried_cost": round(carried_c, 2),
            "added_cost": round(added_c, 2),
            "charge_total": round(charge_tot, 2),
            "batch_total": round(batch_tot, 2),
            "unit_cost": round(u_cost, 2),
            "items": clean_items,
            "charges": b_charges
        }
        processed_batches.append(b_dict)

        # Product-wise aggregation
        if p_name not in product_agg:
            product_agg[p_name] = {
                "product": p_name,
                "belt_type": b_type,
                "dimensions": f"{round(length, 1)} × {round(width, 1)} mm" if length > 0 and width > 0 else "Roll Fabric",
                "stage1_qty": 0.0,
                "stage2_qty": 0.0,
                "stage3_qty": 0.0,
                "stage4_qty": 0.0,
                "total_produced": 0.0,
                "total_accepted": 0.0,
                "total_rejected": 0.0,
                "total_cost": 0.0,
                "batch_count": 0,
                "batches": []
            }
        pa = product_agg[p_name]
        pa["batch_count"] += 1
        pa["batches"].append(b_name)
        pa["total_produced"] += qty
        pa["total_accepted"] += acc_q
        pa["total_rejected"] += rej_q
        pa["total_cost"] += batch_tot
        if stg_num == 1:
            pa["stage1_qty"] += qty
        elif stg_num == 2:
            pa["stage2_qty"] += qty
        elif stg_num == 3:
            pa["stage3_qty"] += qty
        elif stg_num == 4:
            pa["stage4_qty"] += qty

        # Date-wise aggregation
        if p_date not in date_agg:
            date_agg[p_date] = {
                "date": p_date,
                "batches_count": 0,
                "total_planned": 0.0,
                "total_produced": 0.0,
                "total_accepted": 0.0,
                "total_rejected": 0.0,
                "total_cost": 0.0,
                "batches": []
            }
        da = date_agg[p_date]
        da["batches_count"] += 1
        da["total_planned"] += qty
        da["total_produced"] += qty
        da["total_accepted"] += acc_q
        da["total_rejected"] += rej_q
        da["total_cost"] += batch_tot
        da["batches"].append(b_name)

    # 5. Format Material Consumption Rows
    material_consumption_list = []
    for m_code, md in sorted(material_map.items(), key=lambda x: x[1]["total_cost"], reverse=True):
        t_qty = md["total_consumed"]
        t_cost = md["total_cost"]
        avg_r = t_cost / t_qty if t_qty > 0 else 0.0
        material_consumption_list.append({
            "product": m_code,
            "total_consumed": round(t_qty, 3),
            "total_cost": round(t_cost, 2),
            "avg_rate": round(avg_r, 2),
            "batches_count": len(md["batches_used"]),
            "batches_used": md["batches_used"],
            "is_intermediate": md["is_intermediate"]
        })

    # 6. Format Product Summary Rows
    product_summary_list = []
    for p_name, pa in sorted(product_agg.items(), key=lambda x: x[1]["total_cost"], reverse=True):
        avg_u = pa["total_cost"] / pa["total_accepted"] if pa["total_accepted"] > 0 else 0.0
        product_summary_list.append({
            "product": p_name,
            "belt_type": pa["belt_type"],
            "dimensions": pa["dimensions"],
            "stage1_qty": round(pa["stage1_qty"], 3),
            "stage2_qty": round(pa["stage2_qty"], 3),
            "stage3_qty": round(pa["stage3_qty"], 3),
            "stage4_qty": round(pa["stage4_qty"], 3),
            "total_produced": round(pa["total_produced"], 3),
            "total_accepted": round(pa["total_accepted"], 3),
            "total_rejected": round(pa["total_rejected"], 3),
            "total_cost": round(pa["total_cost"], 2),
            "avg_unit_cost": round(avg_u, 2),
            "batch_count": pa["batch_count"],
            "batches": pa["batches"]
        })

    # 7. Format Date Summary Rows
    date_summary_list = []
    for p_date, da in sorted(date_agg.items(), key=lambda x: x[0], reverse=True):
        avg_u = da["total_cost"] / da["total_accepted"] if da["total_accepted"] > 0 else 0.0
        date_summary_list.append({
            "date": p_date,
            "batches_count": da["batches_count"],
            "total_planned": round(da["total_planned"], 3),
            "total_produced": round(da["total_produced"], 3),
            "total_accepted": round(da["total_accepted"], 3),
            "total_rejected": round(da["total_rejected"], 3),
            "total_cost": round(da["total_cost"], 2),
            "avg_unit_cost": round(avg_u, 2),
            "batches": da["batches"]
        })

    # 8. Overall KPIs
    overall_avg_cost = total_cost_all / total_accepted_all if total_accepted_all > 0 else 0.0
    overall_rej_rate = (total_rejected_all / total_produced_all * 100.0) if total_produced_all > 0 else 0.0

    return {
        "success": True,
        "from_date": from_date or "",
        "to_date": to_date or "",
        "batches": processed_batches,
        "product_summary": product_summary_list,
        "date_summary": date_summary_list,
        "material_consumption": material_consumption_list,
        "roll_consumption": {
            "summary": {
                "total_roll_produced": round(total_roll_produced, 3),
                "total_roll_consumed": round(total_roll_consumed, 3),
                "total_roll_required": round(total_roll_required, 3),
                "total_roll_wastage": round(total_roll_wastage, 3),
                "available_roll_balance": round(max(0.0, total_roll_produced - total_roll_consumed), 3),
            },
            "batches": processed_batches
        },
        "rejection_summary": {
            "total_planned": round(total_planned_all, 3),
            "total_produced": round(total_produced_all, 3),
            "total_accepted": round(total_accepted_all, 3),
            "total_rejected": round(total_rejected_all, 3),
            "rejection_rate": round(overall_rej_rate, 2),
            "total_wastage_qty": round(total_wastage_all, 3),
            "total_rejection_cost": round(total_rejection_cost_all, 2),
            "batches": processed_batches
        },
        "cost_summary": {
            "total_carried_cost": round(total_carried_all, 2),
            "total_added_cost": round(total_added_all, 2),
            "total_charges": round(total_charges_all, 2),
            "total_cost": round(total_cost_all, 2),
            "avg_unit_cost": round(overall_avg_cost, 2),
            "batches": processed_batches
        },
        "summary": {
            "total_batches": len(processed_batches),
            "total_planned": round(total_planned_all, 3),
            "total_produced": round(total_produced_all, 3),
            "total_accepted": round(total_accepted_all, 3),
            "total_roll_consumed": round(total_roll_consumed, 3),
            "total_rejected": round(total_rejected_all, 3),
            "total_cost": round(total_cost_all, 2),
            "avg_unit_cost": round(overall_avg_cost, 2)
        }
    }

# ============================================================================
# REPORT: PENDING DISPATCH ANALYSIS & PRICE ANALYSIS APIS
# ============================================================================

@frappe.whitelist()
def get_pending_dispatch_analysis(
    from_date=None,
    to_date=None,
    customer=None,
    sales_order=None,
    product=None,
    product_code=None,
    production_code=None,
    sales_person=None,
    order_status=None,
    include_completed=0,
):
    """
    Pending Dispatch Analysis Report:
    Shows all Sales Orders where an order has been approved but the ordered quantity
    has not been fully dispatched.
    Only confirmed dispatches (dispatch_status = 'Dispatched' AND docstatus != 2) are counted.
    Excludes cancelled Sales Orders (status != 'Cancelled' AND docstatus != 2).
    """
    user = frappe.session.user
    sp = get_current_sales_person(user)
    admin = is_admin(user)

    # 1. Fetch confirmed dispatches aggregated by Sales Order Item row
    dsp_receipts = frappe.db.sql("""
        SELECT 
            di.order_item,
            SUM(di.quantity) as total_dispatched
        FROM `tabDispatch Item` di
        JOIN `tabDispatch` d ON d.name = di.parent
        WHERE d.dispatch_status = 'Dispatched' AND d.docstatus != 2
        GROUP BY di.order_item
    """, as_dict=True)
    dsp_map = {r.order_item: flt(r.total_dispatched) for r in dsp_receipts}

    conditions = ["so.status NOT IN ('Cancelled', 'Rejected')", "so.docstatus != 2"]
    values = {}

    # Sales person security: Sales Person users can only see their authorized sales records
    if not admin and sp:
        conditions.append("so.sales_person = %(current_sp)s")
        values["current_sp"] = sp.name
    elif not admin and not sp:
        return {
            "rows": [],
            "summary": {
                "total_pending_orders": 0,
                "total_ordered_qty": 0.0,
                "total_dispatched_qty": 0.0,
                "total_pending_dispatch_qty": 0.0,
                "total_pending_amount": 0.0,
                "total_rows": 0,
            },
            "customers": [],
            "products": [],
            "sales_persons": [],
            "order_statuses": [],
        }

    # Filters
    if from_date:
        conditions.append("so.order_date >= %(from_date)s")
        values["from_date"] = from_date
    if to_date:
        conditions.append("so.order_date <= %(to_date)s")
        values["to_date"] = to_date
    if customer and str(customer).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("so.customer = %(customer)s")
        values["customer"] = customer
    if sales_order and str(sales_order).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("so.name LIKE %(sales_order)s")
        values["sales_order"] = f"%{sales_order.strip()}%"
    if product and str(product).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("(p.product_name LIKE %(product)s OR soi.product LIKE %(product)s)")
        values["product"] = f"%{product.strip()}%"
    if product_code and str(product_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("soi.product = %(product_code)s")
        values["product_code"] = product_code
    if production_code and str(production_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("p.production_code = %(production_code)s")
        values["production_code"] = production_code
    if sales_person and str(sales_person).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("so.sales_person = %(sales_person)s")
        values["sales_person"] = sales_person
    if order_status and str(order_status).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("so.status = %(order_status)s")
        values["order_status"] = order_status

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT 
            so.name as sales_order_id,
            so.order_date,
            so.customer,
            c.customer_name,
            so.status as order_status,
            so.sales_person,
            sp.sales_person_name,
            soi.name as item_row_name,
            soi.product as product_code,
            p.product_name,
            p.production_code,
            soi.uom,
            soi.quantity as ordered_qty,
            soi.rate,
            soi.amount as total_order_amount
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        LEFT JOIN `tabCustomer` c ON c.name = so.customer
        LEFT JOIN `tabProduct` p ON p.name = soi.product
        LEFT JOIN `tabSales Person` sp ON sp.name = so.sales_person
        WHERE {where_clause}
        ORDER BY so.order_date DESC, so.creation DESC, so.name DESC
    """
    raw_rows = frappe.db.sql(query, values, as_dict=True)

    rows = []
    tot_ordered = 0.0
    tot_dispatched = 0.0
    tot_pending = 0.0
    tot_pending_amount = 0.0
    pending_order_ids = set()

    inc_comp = 1 if include_completed in ("1", 1, "true", "True", True) else 0

    for r in raw_rows:
        ordered = flt(r.ordered_qty)
        dispatched = dsp_map.get(r.item_row_name, 0.0)
        pending = max(0.0, ordered - dispatched)

        if not inc_comp and pending <= 0.000001:
            continue

        rate = flt(r.rate)
        total_order_amt = round(ordered * rate, 2)
        dispatched_amt = round(dispatched * rate, 2)
        pending_amt = round(pending * rate, 2)

        customer_display = r.customer_name or r.customer or "Unknown Customer"
        prod_display = r.product_name or r.product_code or ""

        rows.append({
            "sales_order_date": str(r.order_date) if r.order_date else "",
            "sales_order_id": r.sales_order_id,
            "customer_id": r.customer,
            "customer_name": customer_display,
            "product_name": prod_display,
            "product_code": r.product_code,
            "production_code": r.production_code or "",
            "ordered_qty": ordered,
            "dispatched_qty": dispatched,
            "pending_qty": pending,
            "uom": r.uom or "",
            "rate": rate,
            "total_order_amount": total_order_amt,
            "dispatched_amount": dispatched_amt,
            "pending_amount": pending_amt,
            "order_status": r.order_status or "Draft",
            "expected_delivery_date": "",
            "sales_person": r.sales_person_name or r.sales_person or "",
        })

        tot_ordered += ordered
        tot_dispatched += dispatched
        tot_pending += pending
        tot_pending_amount += pending_amt
        if pending > 0.000001:
            pending_order_ids.add(r.sales_order_id)

    # Master lists for dropdown filters
    customer_list = frappe.db.sql("SELECT name, customer_name FROM `tabCustomer` ORDER BY customer_name ASC", as_dict=True)
    product_list = frappe.db.sql("SELECT name, product_name, production_code FROM `tabProduct` ORDER BY product_name ASC", as_dict=True)
    sp_list = frappe.db.sql("SELECT name, sales_person_name FROM `tabSales Person` ORDER BY sales_person_name ASC", as_dict=True)

    customers = [{"value": "ALL", "label": "All Customers"}] + [
        {"value": c.name, "label": c.customer_name or c.name} for c in customer_list
    ]
    products = [{"value": "ALL", "label": "All Products"}] + [
        {"value": p.name, "label": f"{p.name} - {p.product_name}" if p.product_name else p.name} for p in product_list
    ]
    sales_persons = [{"value": "ALL", "label": "All Sales Persons"}] + [
        {"value": sp_item.name, "label": sp_item.sales_person_name or sp_item.name} for sp_item in sp_list
    ]
    order_statuses = [
        {"value": "ALL", "label": "All Statuses"},
        {"value": "Approved", "label": "Approved"},
        {"value": "Partially Dispatched", "label": "Partially Dispatched"},
        {"value": "Pending Approval", "label": "Pending Approval"},
        {"value": "Completed", "label": "Completed"},
    ]

    return {
        "rows": rows,
        "summary": {
            "total_pending_orders": len(pending_order_ids),
            "total_ordered_qty": round(tot_ordered, 4),
            "total_dispatched_qty": round(tot_dispatched, 4),
            "total_pending_dispatch_qty": round(tot_pending, 4),
            "total_pending_amount": round(tot_pending_amount, 2),
            "total_rows": len(rows),
        },
        "customers": customers,
        "products": products,
        "sales_persons": sales_persons,
        "order_statuses": order_statuses,
    }


@frappe.whitelist()
def get_price_analysis(
    report_type="purchase",
    from_date=None,
    to_date=None,
    product=None,
    product_code=None,
    category=None,
    uom=None,
    vendor=None,
    purchase_entry=None,
    customer=None,
    sales_order=None,
    dispatch_id=None,
    sales_person=None,
):
    """
    Purchase & Selling Price Analysis Report:
    Displays the latest purchase price or latest selling price of each product,
    along with associated vendor/customer and transaction date, plus min and max rates in date range.
    """
    user = frappe.session.user
    sp = get_current_sales_person(user)
    admin = is_admin(user)

    is_purchase = (str(report_type).lower() == "purchase")

    if is_purchase:
        conditions = ["pe.status NOT IN ('Draft', 'Cancelled', 'Rejected')", "pe.docstatus != 2"]
        values = {}

        if from_date:
            conditions.append("pe.posting_date >= %(from_date)s")
            values["from_date"] = from_date
        if to_date:
            conditions.append("pe.posting_date <= %(to_date)s")
            values["to_date"] = to_date
        if vendor and str(vendor).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("pe.vendor = %(vendor)s")
            values["vendor"] = vendor
        if purchase_entry and str(purchase_entry).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("pe.name LIKE %(purchase_entry)s")
            values["purchase_entry"] = f"%{purchase_entry.strip()}%"
        if product and str(product).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("(p.product_name LIKE %(product)s OR pei.product LIKE %(product)s)")
            values["product"] = f"%{product.strip()}%"
        if product_code and str(product_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("pei.product = %(product_code)s")
            values["product_code"] = product_code
        if category and str(category).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("p.category = %(category)s")
            values["category"] = category
        if uom and str(uom).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("pei.uom = %(uom)s")
            values["uom"] = uom

        query = f"""
            SELECT 
                pe.name as purchase_entry_id,
                pe.posting_date,
                pe.creation,
                pe.vendor,
                v.vendor_name,
                pei.product as product_code,
                p.product_name,
                p.category,
                pei.quantity as purchase_qty,
                pei.rate as purchase_rate,
                pei.uom
            FROM `tabPurchase Entry Item` pei
            JOIN `tabPurchase Entry` pe ON pe.name = pei.parent
            LEFT JOIN `tabVendor` v ON v.name = pe.vendor
            LEFT JOIN `tabProduct` p ON p.name = pei.product
            WHERE {" AND ".join(conditions)}
            ORDER BY pe.posting_date DESC, pe.creation DESC, pe.name DESC
        """
        raw_purchases = frappe.db.sql(query, values, as_dict=True)

        by_product = {}
        for r in raw_purchases:
            pcode = r.product_code
            rate = flt(r.purchase_rate)
            if pcode not in by_product:
                by_product[pcode] = {
                    "latest": r,
                    "rates": [rate],
                }
            else:
                by_product[pcode]["rates"].append(rate)

        rows = []
        tot_latest_val = 0.0
        all_min_rates = []
        all_max_rates = []

        for pcode, data in by_product.items():
            lat = data["latest"]
            rates = data["rates"]
            last_rate = flt(lat.purchase_rate)
            min_rate = min(rates)
            max_rate = max(rates)
            qty = flt(lat.purchase_qty)
            val = round(qty * last_rate, 2)

            rows.append({
                "product_name": lat.product_name or pcode,
                "product_code": pcode,
                "vendor_name": lat.vendor_name or lat.vendor or "Unknown Vendor",
                "vendor_id": lat.vendor,
                "last_purchase_date": str(lat.posting_date) if lat.posting_date else "",
                "purchase_entry_id": lat.purchase_entry_id,
                "purchase_qty": qty,
                "last_purchase_rate": last_rate,
                "min_purchase_rate": min_rate,
                "max_purchase_rate": max_rate,
                "purchase_uom": lat.uom or "",
                "currency": "₹",
                "category": lat.category or "",
                "latest_value": val,
            })
            tot_latest_val += val
            all_min_rates.append(min_rate)
            all_max_rates.append(max_rate)

        rows.sort(key=lambda x: (x["product_name"] or "").lower())

        summary = {
            "total_products": len(rows),
            "latest_total_value": round(tot_latest_val, 2),
            "min_rate": min(all_min_rates) if all_min_rates else 0.0,
            "max_rate": max(all_max_rates) if all_max_rates else 0.0,
        }

    else:
        # Selling Wise
        conditions = ["d.dispatch_status = 'Dispatched'", "d.docstatus != 2"]
        values = {}

        if not admin and sp:
            conditions.append("so.sales_person = %(current_sp)s")
            values["current_sp"] = sp.name
        elif not admin and not sp:
            return {
                "rows": [],
                "summary": {"total_products": 0, "latest_total_value": 0.0, "min_rate": 0.0, "max_rate": 0.0},
                "categories": [], "uoms": [], "vendors": [], "customers": [], "sales_persons": [],
            }

        if from_date:
            conditions.append("d.dispatch_date >= %(from_date)s")
            values["from_date"] = from_date
        if to_date:
            conditions.append("d.dispatch_date <= %(to_date)s")
            values["to_date"] = to_date
        if customer and str(customer).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("d.customer = %(customer)s")
            values["customer"] = customer
        if sales_order and str(sales_order).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("d.sales_order LIKE %(sales_order)s")
            values["sales_order"] = f"%{sales_order.strip()}%"
        if dispatch_id and str(dispatch_id).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("d.name LIKE %(dispatch_id)s")
            values["dispatch_id"] = f"%{dispatch_id.strip()}%"
        if sales_person and str(sales_person).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("so.sales_person = %(sales_person)s")
            values["sales_person"] = sales_person
        if product and str(product).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("(p.product_name LIKE %(product)s OR di.product LIKE %(product)s)")
            values["product"] = f"%{product.strip()}%"
        if product_code and str(product_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("di.product = %(product_code)s")
            values["product_code"] = product_code
        if category and str(category).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("p.category = %(category)s")
            values["category"] = category
        if uom and str(uom).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
            conditions.append("(soi.uom = %(uom)s OR p.uom = %(uom)s)")
            values["uom"] = uom

        query = f"""
            SELECT 
                d.name as dispatch_id,
                d.dispatch_date,
                d.creation,
                d.sales_order as sales_order_id,
                d.customer,
                c.customer_name,
                so.sales_person,
                sp.sales_person_name,
                di.product as product_code,
                p.product_name,
                p.category,
                di.quantity as sold_qty,
                COALESCE(soi.rate, di.unit_cost) as selling_rate,
                COALESCE(soi.uom, p.uom) as uom
            FROM `tabDispatch Item` di
            JOIN `tabDispatch` d ON d.name = di.parent
            LEFT JOIN `tabSales Order` so ON so.name = d.sales_order
            LEFT JOIN `tabSales Order Item` soi ON soi.name = di.order_item
            LEFT JOIN `tabCustomer` c ON c.name = d.customer
            LEFT JOIN `tabProduct` p ON p.name = di.product
            LEFT JOIN `tabSales Person` sp ON sp.name = so.sales_person
            WHERE {" AND ".join(conditions)}
            ORDER BY d.dispatch_date DESC, d.creation DESC, d.name DESC
        """
        raw_sales = frappe.db.sql(query, values, as_dict=True)

        by_product = {}
        for r in raw_sales:
            pcode = r.product_code
            rate = flt(r.selling_rate)
            if pcode not in by_product:
                by_product[pcode] = {
                    "latest": r,
                    "rates": [rate],
                }
            else:
                by_product[pcode]["rates"].append(rate)

        rows = []
        tot_latest_val = 0.0
        all_min_rates = []
        all_max_rates = []

        for pcode, data in by_product.items():
            lat = data["latest"]
            rates = data["rates"]
            last_rate = flt(lat.selling_rate)
            min_rate = min(rates)
            max_rate = max(rates)
            qty = flt(lat.sold_qty)
            val = round(qty * last_rate, 2)

            rows.append({
                "product_name": lat.product_name or pcode,
                "product_code": pcode,
                "customer_name": lat.customer_name or lat.customer or "Unknown Customer",
                "customer_id": lat.customer,
                "last_selling_date": str(lat.dispatch_date) if lat.dispatch_date else "",
                "sales_order_id": lat.sales_order_id or "",
                "dispatch_id": lat.dispatch_id,
                "sold_qty": qty,
                "last_selling_rate": last_rate,
                "min_selling_rate": min_rate,
                "max_selling_rate": max_rate,
                "selling_uom": lat.uom or "",
                "currency": "₹",
                "category": lat.category or "",
                "sales_person": lat.sales_person_name or lat.sales_person or "",
                "latest_value": val,
            })
            tot_latest_val += val
            all_min_rates.append(min_rate)
            all_max_rates.append(max_rate)

        rows.sort(key=lambda x: (x["product_name"] or "").lower())

        summary = {
            "total_products": len(rows),
            "latest_total_value": round(tot_latest_val, 2),
            "min_rate": min(all_min_rates) if all_min_rates else 0.0,
            "max_rate": max(all_max_rates) if all_max_rates else 0.0,
        }

    # Common dropdown metadata
    cat_list = frappe.db.sql("SELECT name, category_name FROM `tabCategory` ORDER BY category_name ASC", as_dict=True)
    uom_list = frappe.db.sql("SELECT name, uom_name FROM `tabUOM` ORDER BY uom_name ASC", as_dict=True)
    vendor_list = frappe.db.sql("SELECT name, vendor_name FROM `tabVendor` ORDER BY vendor_name ASC", as_dict=True)
    cust_list = frappe.db.sql("SELECT name, customer_name FROM `tabCustomer` ORDER BY customer_name ASC", as_dict=True)
    sp_list = frappe.db.sql("SELECT name, sales_person_name FROM `tabSales Person` ORDER BY sales_person_name ASC", as_dict=True)

    return {
        "rows": rows,
        "summary": summary,
        "categories": [{"value": "ALL", "label": "All Categories"}] + [{"value": c.name, "label": c.category_name or c.name} for c in cat_list],
        "uoms": [{"value": "ALL", "label": "All UOMs"}] + [{"value": u.name, "label": u.uom_name or u.name} for u in uom_list],
        "vendors": [{"value": "ALL", "label": "All Vendors"}] + [{"value": v.name, "label": v.vendor_name or v.name} for v in vendor_list],
        "customers": [{"value": "ALL", "label": "All Customers"}] + [{"value": c.name, "label": c.customer_name or c.name} for c in cust_list],
        "sales_persons": [{"value": "ALL", "label": "All Sales Persons"}] + [{"value": s.name, "label": s.sales_person_name or s.name} for s in sp_list],
    }


@frappe.whitelist()
def get_store_inventory(search=None, product_name=None, product_code=None, production_code=None, company_code=None, competitor_company_code=None):
    """
    Store Page: Finished Goods Inventory
    Returns all products with available Finished Goods stock.
    Reads directly from tabInventory where stage='Finished' and stock > 0.
    Available quantity = Finished Goods on-hand stock (which already reflects confirmed dispatches and returns).
    Draft/cancelled dispatches do not touch stock.
    Cost = actual unit_price from existing inventory valuation / costing.
    Permissions: Administrator (full access), Sales Person (read-only).
    """
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    admin = ("Administrator" in roles or "System Manager" in roles or "CS Admin" in roles)
    sp = get_current_sales_person(user)
    is_sales = ("CS Sales" in roles or "Sales Person" in roles or bool(sp))
    is_store = ("CS Store" in roles or "CS Production" in roles or "Store Executive" in roles)

    if not (admin or is_sales or is_store):
        raise frappe.PermissionError(_("You do not have permission to view Store inventory."))

    conditions = ["i.stage = 'Finished'", "i.stock > 0.00001"]
    values = {}

    if product_name and str(product_name).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("p.product_name LIKE %(product_name)s")
        values["product_name"] = f"%{product_name.strip()}%"

    if product_code and str(product_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("(p.product_code LIKE %(product_code)s OR i.product LIKE %(product_code)s)")
        values["product_code"] = f"%{product_code.strip()}%"

    if production_code and str(production_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("p.production_code LIKE %(production_code)s")
        values["production_code"] = f"%{production_code.strip()}%"

    if company_code and str(company_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("p.company_code LIKE %(company_code)s")
        values["company_code"] = f"%{company_code.strip()}%"

    if competitor_company_code and str(competitor_company_code).strip() not in ("All", "ALL", "__ALL__", "", "undefined", "null"):
        conditions.append("p.competitor_company_code LIKE %(competitor_company_code)s")
        values["competitor_company_code"] = f"%{competitor_company_code.strip()}%"

    if search and str(search).strip():
        q = f"%{search.strip()}%"
        conditions.append("""(
            p.product_name LIKE %(search)s OR
            p.product_code LIKE %(search)s OR
            i.product LIKE %(search)s OR
            p.production_code LIKE %(search)s OR
            p.company_code LIKE %(search)s OR
            p.competitor_company_code LIKE %(search)s
        )""")
        values["search"] = q

    query = f"""
        SELECT 
            p.name as product_id,
            p.product_name,
            p.product_code,
            COALESCE(NULLIF(p.production_code, ''), '') as production_code,
            COALESCE(NULLIF(p.competitor_company_code, ''), '') as competitor_company_code,
            COALESCE(NULLIF(p.company_code, ''), '') as company_code,
            i.unit_price as product_cost,
            COALESCE(p.uom, 'PCS') as product_uom,
            i.stock as available_quantity,
            i.total_amount
        FROM `tabInventory` i
        JOIN `tabProduct` p ON p.name = i.product
        WHERE {" AND ".join(conditions)}
        ORDER BY p.product_name ASC
    """
    rows = frappe.db.sql(query, values, as_dict=True)

    total_products = len(rows)
    total_qty = sum(flt(r.available_quantity) for r in rows)
    total_val = sum(flt(r.total_amount) or (flt(r.available_quantity) * flt(r.product_cost)) for r in rows)
    avg_cost = (total_val / total_qty) if total_qty > 0 else 0.0

    return {
        "rows": rows,
        "summary": {
            "total_products": total_products,
            "total_quantity": round(total_qty, 2),
            "total_value": round(total_val, 2),
            "avg_unit_cost": round(avg_cost, 2),
        },
        "is_read_only": not admin,
    }


@frappe.whitelist()
def get_last_selling_price(customer=None, product=None, products=None):
    """
    Customer-wise Last Selling Price:
    Retrieves the most recent confirmed selling rate for (customer, product).
    If no customer-specific history is found, falls back to the most recent selling rate across all customers.
    Considers:
      1. Confirmed Dispatches (dispatch_status = 'Dispatched' AND docstatus != 2)
      2. Valid Sales Orders (status NOT IN ('Draft', 'Cancelled', 'Rejected') AND docstatus != 2)
      3. Valid Quotations (as additional fallback)
    Supports single lookup via `product` or bulk lookup via `products` (JSON list or comma-separated).
    """
    import json
    product_list = []
    if products:
        if isinstance(products, str):
            try:
                product_list = json.loads(products)
            except Exception:
                product_list = [p.strip() for p in products.split(",") if p.strip()]
        elif isinstance(products, (list, tuple)):
            product_list = list(products)
    elif product:
        product_list = [product]

    if not product_list:
        frappe.throw(_("At least one Product is required."))

    results = {}
    for prod_identifier in product_list:
        p_str = str(prod_identifier).strip()
        if not p_str:
            continue

        prod_meta = frappe.db.sql("""
            SELECT name, product_code, product_name, production_code, company_code, competitor_company, competitor_company_code 
            FROM `tabProduct` 
            WHERE name = %s OR product_code = %s 
            LIMIT 1
        """, (p_str, p_str), as_dict=True)

        prod_name = prod_meta[0].name if prod_meta else p_str
        prod_code = prod_meta[0].product_code if prod_meta else p_str
        p_name = prod_meta[0].product_name if prod_meta else ""
        prod_code_val = prod_meta[0].production_code if prod_meta else ""
        comp_code_val = prod_meta[0].company_code if prod_meta else ""
        comp_company_val = prod_meta[0].competitor_company if (prod_meta and hasattr(prod_meta[0], 'competitor_company')) else ""
        competitor_code_val = prod_meta[0].competitor_company_code if prod_meta else ""

        latest_match = None
        is_customer_specific = False

        # 1. Customer-specific check
        if customer:
            disp_row = frappe.db.sql("""
                SELECT 
                    d.name as ref_name,
                    'Dispatch' as ref_type,
                    COALESCE(d.dispatch_date, d.creation) as tx_date,
                    COALESCE(soi.rate, di.unit_cost, 0) as rate
                FROM `tabDispatch Item` di
                JOIN `tabDispatch` d ON d.name = di.parent
                LEFT JOIN `tabSales Order Item` soi ON soi.name = di.order_item
                WHERE d.customer = %s
                  AND (di.product = %s OR di.product = %s)
                  AND d.dispatch_status = 'Dispatched'
                  AND d.docstatus != 2
                  AND COALESCE(soi.rate, di.unit_cost, 0) > 0
                ORDER BY d.dispatch_date DESC, d.creation DESC, d.name DESC
                LIMIT 1
            """, (customer, prod_name, prod_code), as_dict=True)

            so_row = frappe.db.sql("""
                SELECT 
                    so.name as ref_name,
                    'Sales Order' as ref_type,
                    COALESCE(so.order_date, so.creation) as tx_date,
                    soi.rate as rate
                FROM `tabSales Order Item` soi
                JOIN `tabSales Order` so ON so.name = soi.parent
                WHERE so.customer = %s
                  AND (soi.product = %s OR soi.product = %s)
                  AND so.status NOT IN ('Draft', 'Cancelled', 'Rejected')
                  AND so.docstatus != 2
                  AND soi.rate > 0
                ORDER BY so.order_date DESC, so.creation DESC, so.name DESC
                LIMIT 1
            """, (customer, prod_name, prod_code), as_dict=True)

            if disp_row and so_row:
                d_date = str(disp_row[0].tx_date or "")
                s_date = str(so_row[0].tx_date or "")
                latest_match = disp_row[0] if d_date >= s_date else so_row[0]
            elif disp_row:
                latest_match = disp_row[0]
            elif so_row:
                latest_match = so_row[0]

            if latest_match:
                is_customer_specific = True

        # 2. General fallback across ALL customers
        if not latest_match:
            gen_disp = frappe.db.sql("""
                SELECT 
                    d.name as ref_name,
                    'Dispatch' as ref_type,
                    COALESCE(d.dispatch_date, d.creation) as tx_date,
                    COALESCE(soi.rate, di.unit_cost, 0) as rate
                FROM `tabDispatch Item` di
                JOIN `tabDispatch` d ON d.name = di.parent
                LEFT JOIN `tabSales Order Item` soi ON soi.name = di.order_item
                WHERE (di.product = %s OR di.product = %s)
                  AND d.dispatch_status = 'Dispatched'
                  AND d.docstatus != 2
                  AND COALESCE(soi.rate, di.unit_cost, 0) > 0
                ORDER BY d.dispatch_date DESC, d.creation DESC, d.name DESC
                LIMIT 1
            """, (prod_name, prod_code), as_dict=True)

            gen_so = frappe.db.sql("""
                SELECT 
                    so.name as ref_name,
                    'Sales Order' as ref_type,
                    COALESCE(so.order_date, so.creation) as tx_date,
                    soi.rate as rate
                FROM `tabSales Order Item` soi
                JOIN `tabSales Order` so ON so.name = soi.parent
                WHERE (soi.product = %s OR soi.product = %s)
                  AND so.status NOT IN ('Draft', 'Cancelled', 'Rejected')
                  AND so.docstatus != 2
                  AND soi.rate > 0
                ORDER BY so.order_date DESC, so.creation DESC, so.name DESC
                LIMIT 1
            """, (prod_name, prod_code), as_dict=True)

            if gen_disp and gen_so:
                d_date = str(gen_disp[0].tx_date or "")
                s_date = str(gen_so[0].tx_date or "")
                latest_match = gen_disp[0] if d_date >= s_date else gen_so[0]
            elif gen_disp:
                latest_match = gen_disp[0]
            elif gen_so:
                latest_match = gen_so[0]

        if latest_match:
            price = round(flt(latest_match.rate), 2)
            results[p_str] = {
                "customer": customer or "",
                "product": p_str,
                "product_name": p_name,
                "product_code": prod_code,
                "production_code": prod_code_val,
                "company_code": comp_code_val,
                "competitor_company": comp_company_val,
                "competitor_company_code": competitor_code_val,
                "last_selling_price": price,
                "transaction_date": str(latest_match.tx_date)[:10] if latest_match.tx_date else "",
                "source_ref": latest_match.ref_name,
                "ref_type": latest_match.ref_type,
                "formatted_price": f"₹{price:,.2f}",
                "has_history": True,
                "is_customer_specific": is_customer_specific,
            }
        else:
            results[p_str] = {
                "customer": customer or "",
                "product": p_str,
                "product_name": p_name,
                "product_code": prod_code,
                "production_code": prod_code_val,
                "company_code": comp_code_val,
                "competitor_company": comp_company_val,
                "competitor_company_code": competitor_code_val,
                "last_selling_price": 0.0,
                "transaction_date": None,
                "source_ref": None,
                "ref_type": None,
                "formatted_price": "N/A",
                "has_history": False,
                "is_customer_specific": False,
            }

    if product and not products:
        return results.get(str(product).strip(), {})
    return results


# Sales Person Wise Sales Report
from clssurya.reports.sales_person_report import (
    get_sales_person_wise_report,
    get_sales_person_detail_report,
)


@frappe.whitelist()
def get_cnc_production_report(
    from_date=None,
    to_date=None,
    machine=None,
    product=None,
    operator=None,
    shift=None,
    operation_sequence=None,
):
    """
    CNC Department Report (CNC-REQ-005):
    Provides date-wise, machine-wise, employee-wise, shift-wise, and rejection analysis.
    """
    conditions = []
    params = {}

    if from_date:
        conditions.append("production_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date:
        conditions.append("production_date <= %(to_date)s")
        params["to_date"] = to_date
    if machine and machine != "All":
        conditions.append("machine = %(machine)s")
        params["machine"] = machine
    if product and product != "All":
        conditions.append("product = %(product)s")
        params["product"] = product
    if operator and operator != "All":
        conditions.append("operator = %(operator)s")
        params["operator"] = operator
    if shift and shift != "All":
        conditions.append("shift = %(shift)s")
        params["shift"] = shift
    if operation_sequence and operation_sequence != "All":
        conditions.append("operation_sequence = %(operation_sequence)s")
        params["operation_sequence"] = operation_sequence

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = frappe.db.sql(f"""
        SELECT
            name,
            production_date,
            machine,
            operation_sequence,
            operation,
            shift,
            operator,
            product,
            product_name,
            production_batch,
            input_qty,
            qty_processed,
            accepted_qty,
            rejected_qty,
            pending_qty,
            rejection_reason,
            rejection_status,
            total_duration_mins,
            remarks
        FROM `tabCNC Machine Log`
        {where_clause}
        ORDER BY production_date DESC, creation DESC
    """, params, as_dict=True)

    total_input = sum(flt(r.get("input_qty") or 0) for r in rows)
    total_accepted = sum(flt(r.get("accepted_qty") or 0) for r in rows)
    total_rejected = sum(flt(r.get("rejected_qty") or 0) for r in rows)
    total_pending = sum(flt(r.get("pending_qty") or 0) for r in rows)

    # Machine breakdown
    machine_summary = {}
    for r in rows:
        m = r.get("machine") or "Unassigned"
        if m not in machine_summary:
            machine_summary[m] = {"machine": m, "input_qty": 0.0, "accepted_qty": 0.0, "rejected_qty": 0.0, "count": 0}
        machine_summary[m]["input_qty"] += flt(r.get("input_qty") or 0)
        machine_summary[m]["accepted_qty"] += flt(r.get("accepted_qty") or 0)
        machine_summary[m]["rejected_qty"] += flt(r.get("rejected_qty") or 0)
        machine_summary[m]["count"] += 1

    # Shift breakdown
    shift_summary = {}
    for r in rows:
        s = r.get("shift") or "Morning"
        if s not in shift_summary:
            shift_summary[s] = {"shift": s, "accepted_qty": 0.0, "rejected_qty": 0.0, "count": 0}
        shift_summary[s]["accepted_qty"] += flt(r.get("accepted_qty") or 0)
        shift_summary[s]["rejected_qty"] += flt(r.get("rejected_qty") or 0)
        shift_summary[s]["count"] += 1

    # Rejection reasons breakdown
    rejection_summary = {}
    for r in rows:
        if flt(r.get("rejected_qty") or 0) > 0:
            reason = r.get("rejection_reason") or "Unspecified"
            status = r.get("rejection_status") or "Scrap"
            k = f"{reason} ({status})"
            if k not in rejection_summary:
                rejection_summary[k] = {"reason": reason, "status": status, "qty": 0.0, "count": 0}
            rejection_summary[k]["qty"] += flt(r.get("rejected_qty") or 0)
            rejection_summary[k]["count"] += 1

    return {
        "rows": rows,
        "summary": {
            "total_logs": len(rows),
            "total_input": total_input,
            "total_accepted": total_accepted,
            "total_rejected": total_rejected,
            "total_pending": total_pending,
            "rejection_rate": (total_rejected / total_input * 100) if total_input > 0 else 0.0,
        },
        "machine_summary": list(machine_summary.values()),
        "shift_summary": list(shift_summary.values()),
        "rejection_summary": list(rejection_summary.values()),
    }


@frappe.whitelist()
def get_external_grinding_report(
    from_date=None,
    to_date=None,
    vendor=None,
    product=None,
    status=None,
):
    """
    External Grinding Tracking Report (GRIND-REQ-001):
    Outward, inward, accepted, rejected, and vendor-wise pending quantities.
    """
    conditions = []
    params = {}

    if from_date:
        conditions.append("outward_date >= %(from_date)s")
        params["from_date"] = from_date
    if to_date:
        conditions.append("outward_date <= %(to_date)s")
        params["to_date"] = to_date
    if vendor and vendor != "All":
        conditions.append("vendor = %(vendor)s")
        params["vendor"] = vendor
    if product and product != "All":
        conditions.append("product = %(product)s")
        params["product"] = product
    if status and status != "All":
        conditions.append("grinding_status = %(status)s")
        params["status"] = status

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = frappe.db.sql(f"""
        SELECT
            name,
            job_reference,
            product,
            vendor,
            challan_no,
            outward_date,
            sent_qty,
            uom,
            inward_date,
            returned_qty,
            accepted_qty,
            rejected_qty,
            pending_qty,
            rejection_reason,
            grinding_status,
            remarks
        FROM `tabExternal Grinding Log`
        {where_clause}
        ORDER BY outward_date DESC, creation DESC
    """, params, as_dict=True)

    total_sent = sum(flt(r.get("sent_qty") or 0) for r in rows)
    total_returned = sum(flt(r.get("returned_qty") or 0) for r in rows)
    total_accepted = sum(flt(r.get("accepted_qty") or 0) for r in rows)
    total_rejected = sum(flt(r.get("rejected_qty") or 0) for r in rows)
    total_pending = sum(flt(r.get("pending_qty") or 0) for r in rows)

    # Vendor-wise pending summary
    vendor_summary = {}
    for r in rows:
        v = r.get("vendor") or "Unassigned"
        if v not in vendor_summary:
            vendor_summary[v] = {"vendor": v, "sent_qty": 0.0, "returned_qty": 0.0, "pending_qty": 0.0, "count": 0}
        vendor_summary[v]["sent_qty"] += flt(r.get("sent_qty") or 0)
        vendor_summary[v]["returned_qty"] += flt(r.get("returned_qty") or 0)
        vendor_summary[v]["pending_qty"] += flt(r.get("pending_qty") or 0)
        vendor_summary[v]["count"] += 1

    return {
        "rows": rows,
        "summary": {
            "total_entries": len(rows),
            "total_sent": total_sent,
            "total_returned": total_returned,
            "total_accepted": total_accepted,
            "total_rejected": total_rejected,
            "total_pending": total_pending,
        },
        "vendor_summary": list(vendor_summary.values()),
    }


@frappe.whitelist()
def get_bonding_coating_report(from_date=None, to_date=None, shift=None):
    """
    Bonding & Coating Process Report (BOND-REQ-001, COAT-REQ-001):
    Daily output and chemical material consumption.
    """
    b_cond = []
    b_params = {}
    c_cond = []
    c_params = {}

    if from_date:
        b_cond.append("production_date >= %(from_date)s")
        b_params["from_date"] = from_date
        c_cond.append("coating_date >= %(from_date)s")
        c_params["from_date"] = from_date
    if to_date:
        b_cond.append("production_date <= %(to_date)s")
        b_params["to_date"] = to_date
        c_cond.append("coating_date <= %(to_date)s")
        c_params["to_date"] = to_date
    if shift and shift != "All":
        b_cond.append("shift = %(shift)s")
        b_params["shift"] = shift
        c_cond.append("shift = %(shift)s")
        c_params["shift"] = shift

    b_where = f"WHERE {' AND '.join(b_cond)}" if b_cond else ""
    c_where = f"WHERE {' AND '.join(c_cond)}" if c_cond else ""

    bonding_rows = frappe.db.sql(f"""
        SELECT * FROM `tabBonding Log` {b_where} ORDER BY production_date DESC, creation DESC
    """, b_params, as_dict=True)

    coating_rows = frappe.db.sql(f"""
        SELECT * FROM `tabCoating Log` {c_where} ORDER BY coating_date DESC, creation DESC
    """, c_params, as_dict=True)

    return {
        "bonding": {
            "rows": bonding_rows,
            "total_output_kg": sum(flt(r.get("bonding_output_kg") or 0) for r in bonding_rows),
            "total_ipa": sum(flt(r.get("ipa_qty") or 0) for r in bonding_rows),
            "total_resorcinol": sum(flt(r.get("resorcinol_qty") or 0) for r in bonding_rows),
            "total_powder": sum(flt(r.get("nylon_powder_kg") or 0) for r in bonding_rows),
        },
        "coating": {
            "rows": coating_rows,
            "total_meters": sum(flt(r.get("roll_meters_coated") or 0) for r in coating_rows),
            "total_chemicals_kg": sum(flt(r.get("coating_total_kg") or 0) for r in coating_rows),
            "total_hub": sum(flt(r.get("hub_1046m_kg") or 0) for r in coating_rows),
            "total_cl501": sum(flt(r.get("cl_501_kg") or 0) for r in coating_rows),
            "total_tolnue": sum(flt(r.get("tolnue_kg") or 0) for r in coating_rows),
        },
    }

