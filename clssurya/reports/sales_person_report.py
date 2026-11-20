"""
Sales Person Wise Sales Report
Provides aggregated sales metrics per sales person and row-level drill-down details.

Permissions:
- Administrators can see all sales persons and filter across all sales persons.
- Sales Persons can see only their own data (enforced at API level).
"""

import frappe
from frappe.utils import flt
from clssurya.utils.base import is_admin
from clssurya.utils.sales_person import get_current_sales_person


def _clean_filter(val):
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "All", "ALL", "__ALL__", "undefined", "null", "None"):
        return None
    return s


@frappe.whitelist()
def get_sales_person_wise_report(
    from_date=None,
    to_date=None,
    sales_person=None,
    customer=None,
    product_name=None,
    product_code=None,
    order_status=None,
):
    """
    Returns aggregated sales performance per sales person with strict access control:
    - Admin can see all sales persons.
    - Sales person sees only their own data.
    """
    user = frappe.session.user
    admin = is_admin(user)
    current_sp = get_current_sales_person(user)

    # 1. Access Control
    if not admin:
        if not current_sp:
            return {
                "rows": [],
                "summary": {
                    "total_sales_persons": 0,
                    "total_sales_orders": 0,
                    "total_dispatched_qty": 0.0,
                    "total_sales_amount": 0.0,
                    "total_pending_orders": 0,
                    "best_sales_person": "N/A",
                },
                "sales_persons": [],
                "customers": [],
                "products": [],
                "order_statuses": [],
            }
        # Force sales person filter to current logged-in sales person
        sales_person = current_sp.name

    from_date = _clean_filter(from_date)
    to_date = _clean_filter(to_date)
    sales_person = _clean_filter(sales_person)
    customer = _clean_filter(customer)
    product_name = _clean_filter(product_name)
    product_code = _clean_filter(product_code)
    order_status = _clean_filter(order_status)

    # 2. Fetch all confirmed dispatches mapped by sales order item
    dsp_query = """
        SELECT 
            di.order_item,
            d.name as dispatch_name,
            d.sales_order,
            di.quantity,
            di.unit_cost
        FROM `tabDispatch Item` di
        JOIN `tabDispatch` d ON d.name = di.parent
        WHERE d.dispatch_status = 'Dispatched' AND d.docstatus != 2
    """
    dsp_items = frappe.db.sql(dsp_query, as_dict=True)
    dsp_map = {}
    for di in dsp_items:
        oi = di.order_item
        if not oi:
            continue
        if oi not in dsp_map:
            dsp_map[oi] = {"qty": 0.0, "dispatches": set(), "unit_cost": flt(di.unit_cost)}
        dsp_map[oi]["qty"] += flt(di.quantity)
        dsp_map[oi]["dispatches"].add(di.dispatch_name)

    # 3. Query all Sales Persons
    sp_records = frappe.get_all(
        "Sales Person",
        fields=["name", "sales_person_name", "employee_id", "email", "status"],
        filters={"status": "Active"} if not admin else {},
        order_by="sales_person_name asc",
    )
    sp_meta = {sp.name: sp for sp in sp_records}

    # 4. Query Quotations matching filters
    q_conditions = ["q.docstatus != 2"]
    q_values = {}
    if from_date:
        q_conditions.append("q.quotation_date >= %(from_date)s")
        q_values["from_date"] = from_date
    if to_date:
        q_conditions.append("q.quotation_date <= %(to_date)s")
        q_values["to_date"] = to_date
    if customer:
        q_conditions.append("q.customer = %(customer)s")
        q_values["customer"] = customer
    if sales_person:
        q_conditions.append("(q.sales_person = %(sales_person)s OR (q.sales_person IS NULL AND c.sales_person = %(sales_person)s))")
        q_values["sales_person"] = sales_person

    q_join_item = ""
    if product_code or product_name:
        q_join_item = "JOIN `tabQuotation Item` qi ON qi.parent = q.name"
        if product_code:
            q_conditions.append("qi.product = %(product_code)s")
            q_values["product_code"] = product_code
        if product_name:
            q_join_item += " LEFT JOIN `tabProduct` qp ON qp.name = qi.product"
            q_conditions.append("(qp.product_name LIKE %(product_name)s OR qi.product LIKE %(product_name)s)")
            q_values["product_name"] = f"%{product_name}%"

    q_query = f"""
        SELECT DISTINCT
            q.name,
            COALESCE(NULLIF(q.sales_person, ''), c.sales_person, 'Unassigned') as sp_key,
            q.customer
        FROM `tabQuotation` q
        LEFT JOIN `tabCustomer` c ON c.name = q.customer
        {q_join_item}
        WHERE {' AND '.join(q_conditions)}
    """
    q_rows = frappe.db.sql(q_query, q_values, as_dict=True)
    quotations_by_sp = {}
    for q in q_rows:
        sp_key = q.sp_key or "Unassigned"
        quotations_by_sp.setdefault(sp_key, set()).add(q.name)

    # 5. Query Sales Orders and items matching filters
    so_conditions = ["so.status != 'Cancelled'", "so.docstatus != 2"]
    so_values = {}
    if from_date:
        so_conditions.append("so.order_date >= %(from_date)s")
        so_values["from_date"] = from_date
    if to_date:
        so_conditions.append("so.order_date <= %(to_date)s")
        so_values["to_date"] = to_date
    if customer:
        so_conditions.append("so.customer = %(customer)s")
        so_values["customer"] = customer
    if sales_person:
        so_conditions.append("(so.sales_person = %(sales_person)s OR (so.sales_person IS NULL AND c.sales_person = %(sales_person)s))")
        so_values["sales_person"] = sales_person
    if order_status:
        so_conditions.append("so.status = %(order_status)s")
        so_values["order_status"] = order_status
    if product_code:
        so_conditions.append("soi.product = %(product_code)s")
        so_values["product_code"] = product_code
    if product_name:
        so_conditions.append("(p.product_name LIKE %(product_name)s OR soi.product LIKE %(product_name)s)")
        so_values["product_name"] = f"%{product_name}%"

    so_query = f"""
        SELECT 
            so.name as so_name,
            so.order_date,
            so.customer,
            so.status as order_status,
            COALESCE(NULLIF(so.sales_person, ''), c.sales_person, 'Unassigned') as sp_key,
            soi.name as item_name,
            soi.product,
            p.product_name,
            soi.quantity as ordered_qty,
            soi.rate
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        LEFT JOIN `tabCustomer` c ON c.name = so.customer
        LEFT JOIN `tabProduct` p ON p.name = soi.product
        WHERE {' AND '.join(so_conditions)}
        ORDER BY so.order_date DESC, so.name DESC
    """
    so_rows = frappe.db.sql(so_query, so_values, as_dict=True)

    # 6. Aggregate by Sales Person
    so_by_sp = {}
    pending_orders_set = set()

    # Track order-level pending status
    order_items_map = {}

    for r in so_rows:
        sp_key = r.sp_key or "Unassigned"
        if sp_key not in so_by_sp:
            so_by_sp[sp_key] = {
                "sales_orders": set(),
                "customers": set(),
                "dispatches": set(),
                "total_products_sold": 0.0,
                "total_sales_amount": 0.0,
                "total_pending_amount": 0.0,
                "total_completed_amount": 0.0,
                "order_statuses": {},
                "order_pending_map": {},
            }
        agg = so_by_sp[sp_key]
        agg["sales_orders"].add(r.so_name)
        agg["customers"].add(r.customer)
        agg["order_statuses"][r.so_name] = r.order_status

        ordered = flt(r.ordered_qty)
        rate = flt(r.rate)
        disp_info = dsp_map.get(r.item_name, {"qty": 0.0, "dispatches": set()})
        dispatched = disp_info["qty"]
        agg["dispatches"].update(disp_info["dispatches"])

        pending = max(0.0, ordered - dispatched)
        disp_amt = dispatched * rate
        pend_amt = pending * rate

        agg["total_products_sold"] += dispatched
        agg["total_sales_amount"] += disp_amt
        agg["total_pending_amount"] += pend_amt

        if r.so_name not in agg["order_pending_map"]:
            agg["order_pending_map"][r.so_name] = {"pending_total": 0.0, "dispatched_total": 0.0, "amount_dispatched": 0.0}
        agg["order_pending_map"][r.so_name]["pending_total"] += pending
        agg["order_pending_map"][r.so_name]["dispatched_total"] += dispatched
        agg["order_pending_map"][r.so_name]["amount_dispatched"] += disp_amt

        if pending > 0.00001:
            pending_orders_set.add(r.so_name)

    # Compute completed amounts for orders that are fully dispatched or status == 'Completed'
    for sp_key, agg in so_by_sp.items():
        comp_amt = 0.0
        for so_id, op_info in agg["order_pending_map"].items():
            status = agg["order_statuses"].get(so_id, "")
            # If status is explicitly Completed or all items fully dispatched
            if status == "Completed" or (op_info["pending_total"] <= 0.00001 and op_info["dispatched_total"] > 0):
                comp_amt += op_info["amount_dispatched"]
        agg["total_completed_amount"] = comp_amt

    # 7. Construct Report Rows
    # Determine sales persons to include:
    if sales_person:
        target_sps = [sales_person]
    elif admin:
        # Include all known active sales persons + any unassigned with activity
        target_sps = [sp.name for sp in sp_records]
        for sp_k in list(so_by_sp.keys()) + list(quotations_by_sp.keys()):
            if sp_k not in target_sps:
                target_sps.append(sp_k)
    else:
        target_sps = [current_sp.name] if current_sp else []

    rows = []
    tot_orders_all = 0
    tot_disp_qty_all = 0.0
    tot_sales_amt_all = 0.0

    for sp_k in target_sps:
        data = so_by_sp.get(sp_k, {
            "sales_orders": set(),
            "customers": set(),
            "dispatches": set(),
            "total_products_sold": 0.0,
            "total_sales_amount": 0.0,
            "total_pending_amount": 0.0,
            "total_completed_amount": 0.0,
        })
        quotes_set = quotations_by_sp.get(sp_k, set())

        # If filtered by something and this SP has 0 quotations and 0 orders, skip unless SP was explicitly chosen
        if (from_date or to_date or customer or product_name or product_code or order_status) and not sales_person:
            if not quotes_set and not data["sales_orders"]:
                continue

        meta = sp_meta.get(sp_k)
        sp_display_name = meta.sales_person_name if meta else (sp_k if sp_k != "Unassigned" else "Unassigned / General")

        t_orders = len(data["sales_orders"])
        t_sold_qty = round(data["total_products_sold"], 2)
        t_sales_amt = round(data["total_sales_amount"], 2)

        tot_orders_all += t_orders
        tot_disp_qty_all += t_sold_qty
        tot_sales_amt_all += t_sales_amt

        rows.append({
            "sales_person": sp_k,
            "sales_person_name": sp_display_name,
            "employee_id": meta.employee_id if meta else "-",
            "email": meta.email if meta else "-",
            "total_quotations": len(quotes_set),
            "total_sales_orders": t_orders,
            "total_dispatched_orders": len(data["dispatches"]),
            "total_products_sold": t_sold_qty,
            "total_sales_amount": t_sales_amt,
            "total_pending_amount": round(data["total_pending_amount"], 2),
            "total_completed_amount": round(data["total_completed_amount"], 2),
            "total_customers": len(data["customers"]),
        })

    # Sort rows by total_sales_amount DESC
    rows.sort(key=lambda r: r["total_sales_amount"], reverse=True)

    # Best performing sales person
    best_sp = "N/A"
    if rows:
        top_row = max(rows, key=lambda r: (r["total_sales_amount"], r["total_sales_orders"]))
        if top_row["total_sales_amount"] > 0 or top_row["total_sales_orders"] > 0:
            best_sp = top_row["sales_person_name"]

    summary = {
        "total_sales_persons": len(rows),
        "total_sales_orders": tot_orders_all,
        "total_dispatched_qty": round(tot_disp_qty_all, 2),
        "total_sales_amount": round(tot_sales_amt_all, 2),
        "total_pending_orders": len(pending_orders_set),
        "best_performing_sales_person": best_sp,
    }

    # Filter dropdown options
    customers_data = frappe.db.sql("SELECT name, customer_name FROM `tabCustomer` ORDER BY customer_name ASC", as_dict=True)
    products_data = frappe.db.sql("SELECT name, product_name FROM `tabProduct` ORDER BY product_name ASC", as_dict=True)

    sales_persons_options = [{"value": "ALL", "label": "All Sales Persons"}] + [
        {"value": sp.name, "label": sp.sales_person_name or sp.name} for sp in sp_records
    ]
    customers_options = [{"value": "ALL", "label": "All Customers"}] + [
        {"value": c.name, "label": c.customer_name or c.name} for c in customers_data
    ]
    products_options = [{"value": "ALL", "label": "All Products"}] + [
        {"value": p.name, "label": f"{p.name} - {p.product_name}" if p.product_name else p.name} for p in products_data
    ]
    order_statuses_options = [
        {"value": "ALL", "label": "All Statuses"},
        {"value": "Approved", "label": "Approved"},
        {"value": "Partially Dispatched", "label": "Partially Dispatched"},
        {"value": "Pending Approval", "label": "Pending Approval"},
        {"value": "Completed", "label": "Completed"},
    ]

    return {
        "rows": rows,
        "summary": summary,
        "sales_persons": sales_persons_options,
        "customers": customers_options,
        "products": products_options,
        "order_statuses": order_statuses_options,
    }


@frappe.whitelist()
def get_sales_person_detail_report(
    sales_person=None,
    from_date=None,
    to_date=None,
    customer=None,
    product_name=None,
    product_code=None,
    order_status=None,
):
    """
    Returns row-level detail breakdown for a specific sales person.
    Permissions:
    - Admin can specify any sales person.
    - Sales person is strictly forced to their own profile.
    """
    user = frappe.session.user
    admin = is_admin(user)
    current_sp = get_current_sales_person(user)

    if not admin:
        if not current_sp:
            return {"rows": []}
        sales_person = current_sp.name

    sales_person = _clean_filter(sales_person)
    from_date = _clean_filter(from_date)
    to_date = _clean_filter(to_date)
    customer = _clean_filter(customer)
    product_name = _clean_filter(product_name)
    product_code = _clean_filter(product_code)
    order_status = _clean_filter(order_status)

    if not sales_person:
        return {"rows": []}

    # 1. Confirmed dispatches per item
    dsp_items = frappe.db.sql("""
        SELECT 
            di.order_item,
            d.name as dispatch_name,
            di.quantity
        FROM `tabDispatch Item` di
        JOIN `tabDispatch` d ON d.name = di.parent
        WHERE d.dispatch_status = 'Dispatched' AND d.docstatus != 2
    """, as_dict=True)
    dsp_map = {}
    for di in dsp_items:
        oi = di.order_item
        if oi:
            dsp_map[oi] = dsp_map.get(oi, 0.0) + flt(di.quantity)

    # 2. Build detail query
    conditions = [
        "so.status != 'Cancelled'",
        "so.docstatus != 2",
    ]
    values = {}

    if sales_person == "Unassigned":
        conditions.append("(so.sales_person IS NULL OR so.sales_person = '') AND (c.sales_person IS NULL OR c.sales_person = '')")
    else:
        conditions.append("(so.sales_person = %(sales_person)s OR (so.sales_person IS NULL AND c.sales_person = %(sales_person)s))")
        values["sales_person"] = sales_person

    if from_date:
        conditions.append("so.order_date >= %(from_date)s")
        values["from_date"] = from_date
    if to_date:
        conditions.append("so.order_date <= %(to_date)s")
        values["to_date"] = to_date
    if customer:
        conditions.append("so.customer = %(customer)s")
        values["customer"] = customer
    if order_status:
        conditions.append("so.status = %(order_status)s")
        values["order_status"] = order_status
    if product_code:
        conditions.append("soi.product = %(product_code)s")
        values["product_code"] = product_code
    if product_name:
        conditions.append("(p.product_name LIKE %(product_name)s OR soi.product LIKE %(product_name)s)")
        values["product_name"] = f"%{product_name}%"

    detail_query = f"""
        SELECT 
            COALESCE(NULLIF(so.sales_person, ''), c.sales_person, 'Unassigned') as sp_id,
            sp.sales_person_name,
            so.quotation as quotation_number,
            so.name as sales_order_number,
            COALESCE(c.customer_name, so.customer) as customer_name,
            so.order_date,
            p.product_name,
            soi.product as product_code,
            soi.quantity as ordered_qty,
            soi.rate,
            soi.amount as total_amount,
            so.status as order_status,
            soi.name as item_name
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        LEFT JOIN `tabCustomer` c ON c.name = so.customer
        LEFT JOIN `tabProduct` p ON p.name = soi.product
        LEFT JOIN `tabSales Person` sp ON sp.name = COALESCE(NULLIF(so.sales_person, ''), c.sales_person)
        WHERE {' AND '.join(conditions)}
        ORDER BY so.order_date DESC, so.name DESC
    """
    raw_details = frappe.db.sql(detail_query, values, as_dict=True)

    rows = []
    for r in raw_details:
        ordered = flt(r.ordered_qty)
        dispatched = dsp_map.get(r.item_name, 0.0)
        pending = max(0.0, ordered - dispatched)
        rate = flt(r.rate)
        total_amt = round(ordered * rate, 2) if r.total_amount is None else round(flt(r.total_amount), 2)

        if pending <= 0.00001 and dispatched > 0:
            disp_status = "Fully Dispatched"
        elif dispatched > 0 and pending > 0:
            disp_status = "Partially Dispatched"
        else:
            disp_status = "Pending Dispatch"

        rows.append({
            "sales_person_name": r.sales_person_name or r.sp_id or "Unassigned",
            "quotation_number": r.quotation_number or "-",
            "sales_order_number": r.sales_order_number,
            "customer_name": r.customer_name,
            "order_date": str(r.order_date) if r.order_date else "-",
            "product_name": r.product_name or r.product_code or "-",
            "product_code": r.product_code or "-",
            "ordered_qty": ordered,
            "dispatched_qty": dispatched,
            "pending_qty": pending,
            "rate": rate,
            "total_amount": total_amt,
            "dispatch_status": disp_status,
            "order_status": r.order_status or "Draft",
        })

    return {"rows": rows}

