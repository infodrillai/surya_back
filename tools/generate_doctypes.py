"""Generates every DocType JSON in clssurya/clssurya/doctype/. Run: python tools/generate_doctypes.py"""
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "clssurya", "clssurya", "doctype")
NUM = ("Float", "Currency", "Percent")
STAGES = "Raw\nStage 1\nStage 2\nStage 3\nFinished"
ADMIN, STORE, PROD, SALES = "CS Admin", "CS Store", "CS Production", "CS Sales"


def F(fn, ft="Data", label=None, **kw):
    d = {"fieldname": fn, "fieldtype": ft, "label": label or fn.replace("_", " ").title()}
    if ft in NUM and "precision" not in kw:
        d["precision"] = "9"  # store full precision, round only for display
    d.update(kw)
    return d


def P(full=(), read=()):
    rows = [{"role": r, "read": 1, "write": 1, "create": 1, "delete": 1} for r in ("System Manager", ADMIN, *full)]
    return rows + [{"role": r, "read": 1} for r in read]


ALL = (STORE, PROD, SALES)
DONE = [F("is_completed", "Check", read_only=1, default=0, in_list_view=1, no_copy=1),
        F("completed_on", "Datetime", read_only=1, no_copy=1),
        F("completed_by", "Link", options="User", read_only=1, no_copy=1)]
RO = dict(read_only=1)


def master(name, label_field, extra=(), perms=None):
    return dict(name=name, autoname=f"field:{label_field}", perms=perms or P(read=ALL),
                fields=[F(label_field, reqd=1, unique=1, in_list_view=1), *extra])


contact = [F("gstin", "Data", "GSTIN"), F("state"), F("phone"), F("address", "Small Text")]
carried = [F("is_carried_in", "Check", read_only=1, default=0), F("process", "Link", options="Process"),
           F("product", "Link", options="Product", reqd=1), F("per_unit_utilization", "Float"),
           F("total_utilization", "Float", **RO), F("actual_utilization", "Float"), F("unit_price", "Currency", **RO),
           F("amount", "Currency", **RO), F("per_unit_amount", "Currency", **RO), F("actual_amount", "Currency", **RO)]
cost = lambda: [F("carried_cost", "Currency", **RO), F("added_cost", "Currency", **RO), F("rejection_percent", "Percent"),
                F("rejection_amount", "Currency", **RO), F("batch_total", "Currency", **RO), F("unit_cost", "Currency", in_list_view=1, **RO)]
head = lambda: [F("product", "Link", options="Product", reqd=1, in_list_view=1), F("quantity", "Float", reqd=1, in_list_view=1),
                F("posting_date", "Date")]

DT = [
    master("UOM", "uom_name", perms=P(read=ALL)),
    master("Process", "process_name", perms=P(read=(STORE, PROD))),
    master("Category", "category_name"),
    master("Charge", "charge_name", perms=P(read=(PROD,))),
    master("Vendor", "vendor_name", contact, P(full=(STORE,), read=(PROD,))),
    master("Customer", "customer_name", contact, P(full=(SALES,), read=(STORE,))),
    dict(name="Product", autoname="field:product_code", perms=P(read=ALL), fields=[
        F("product_name", reqd=1, in_list_view=1), F("product_code", reqd=1, unique=1, in_list_view=1),
        F("product_type", "Select", options="Raw\nSemi\nFinished", reqd=1, in_list_view=1),
        F("uom", "Link", "UOM", options="UOM", reqd=1), F("is_scrap", "Check"),
        F("low_stock_limit", "Float"), F("high_stock_limit", "Float"), F("category", "Link", options="Category"),
        F("total_steps", "Int", depends_on="eval:doc.product_type!='Raw'"), F("allow_negative_stock", "Check")]),
    dict(name="BOM", autoname="field:product", perms=P(read=(PROD,)), fields=[
        F("product", "Link", options="Product", reqd=1, unique=1, in_list_view=1),
        F("total_steps", "Int", read_only=1, fetch_from="product.total_steps"),
        F("stage1_items", "Table", "Stage 1 Items", options="BOM Stage 1 Item"),
        F("stage2_items", "Table", "Stage 2 Items", options="BOM Stage 2 Item"),
        F("stage3_charges", "Table", "Stage 3 Charges", options="BOM Stage 3 Charge")]),
    dict(name="BOM Stage 1 Item", child=1, fields=[F("process", "Link", options="Process"), F("product", "Link", options="Product", reqd=1, in_list_view=1),
         F("per_unit_utilization", "Float", in_list_view=1), F("wastage_product", "Link", options="Product")]),
    dict(name="BOM Stage 2 Item", child=1, fields=[F("process", "Link", options="Process"), F("product", "Link", options="Product", reqd=1, in_list_view=1),
         F("per_unit_utilization", "Float", in_list_view=1)]),
    dict(name="BOM Stage 3 Charge", child=1, fields=[F("charge", "Link", options="Charge", reqd=1, in_list_view=1), F("per_unit_price", "Currency", in_list_view=1)]),
    dict(name="Purchase Entry", autoname="format:PUR-{#####}", tx=1, perms=P(full=(STORE,)), fields=[
        F("vendor", "Link", options="Vendor", reqd=1, in_list_view=1), F("posting_date", "Date", reqd=1, in_list_view=1),
        F("bill_no", reqd=1), F("vendor_state", "Data", **RO), F("items", "Table", options="Purchase Entry Item"),
        F("taxable_amount", "Currency", **RO), F("tax_amount", "Currency", **RO), F("extra_charges", "Currency"),
        F("grand_total", "Currency", in_list_view=1, **RO), *DONE]),
    dict(name="Purchase Entry Item", child=1, fields=[F("product", "Link", options="Product", reqd=1, in_list_view=1), F("quantity", "Float", in_list_view=1),
         F("uom", "Link", options="UOM", read_only=1), F("rate", "Currency", in_list_view=1), F("gst_percent", "Percent"),
         F("amount", "Currency", **RO), F("cgst", "Currency", **RO), F("sgst", "Currency", **RO), F("igst", "Currency", **RO), F("landed_rate", "Currency", **RO)]),
    dict(name="Stage 1 Batch", autoname="format:S1B-{#####}", tx=1, perms=P(full=(PROD,), read=(STORE,)), fields=[
        *head(), F("items", "Table", options="Stage 1 Batch Item"), F("weight_per_piece", "Float"),
        F("wastage_product", "Link", options="Product"), F("wastage_qty", "Float", **RO), *cost(), *DONE]),
    dict(name="Stage 1 Batch Item", child=1, fields=[f for f in carried if f["fieldname"] != "is_carried_in"]),
    dict(name="Stage 2 Batch", autoname="format:S2B-{#####}", tx=1, perms=P(full=(PROD,), read=(STORE,)), fields=[
        *head(), F("items", "Table", options="Stage 2 Batch Item"), *cost(), *DONE]),
    dict(name="Stage 2 Batch Item", child=1, fields=carried),
    dict(name="Stage 3 Batch", autoname="format:S3B-{#####}", tx=1, perms=P(full=(PROD,), read=(STORE,)), fields=[
        *head(), F("items", "Table", options="Stage 2 Batch Item"), F("charges", "Table", options="Stage 3 Batch Charge"), *cost(), *DONE]),
    dict(name="Stage 3 Batch Charge", child=1, fields=[F("charge", "Link", options="Charge", reqd=1, in_list_view=1),
         F("per_unit_price", "Currency", in_list_view=1), F("amount", "Currency", **RO)]),
    dict(name="Quotation", autoname="format:QTN-{#####}", tx=1, perms=P(full=(SALES,)), fields=[
        F("customer", "Link", options="Customer", reqd=1, in_list_view=1), F("quotation_date", "Date"),
        F("version", "Int", default=1, read_only=1), F("parent_quotation", "Link", options="Quotation", read_only=1),
        F("status", "Select", options="Draft\nSent\nSuperseded\nAccepted\nRejected", default="Draft", in_list_view=1),
        F("items", "Table", options="Quotation Item"), F("total_amount", "Currency", in_list_view=1, **RO), F("below_cost", "Check", **RO)]),
    dict(name="Quotation Item", child=1, fields=[F("product", "Link", options="Product", reqd=1, in_list_view=1), F("quantity", "Float", in_list_view=1),
         F("uom", "Link", options="UOM", read_only=1), F("production_cost", "Currency", **RO), F("rate", "Currency", in_list_view=1),
         F("amount", "Currency", **RO), F("below_cost", "Check", **RO)]),
    dict(name="Sales Order", autoname="format:SO-{#####}", tx=1, perms=P(full=(SALES,), read=(STORE,)), fields=[
        F("customer", "Link", options="Customer", reqd=1, in_list_view=1), F("order_date", "Date"), F("quotation", "Link", options="Quotation", read_only=1),
        F("status", "Select", options="Pending Approval\nApproved\nPartially Dispatched\nCompleted", default="Pending Approval", read_only=1, in_list_view=1),
        F("items", "Table", options="Sales Order Item"), F("total_amount", "Currency", **RO), F("below_cost", "Check", **RO),
        F("approved_by", "Link", options="User", read_only=1), F("approved_on", "Datetime", read_only=1), *DONE]),
    dict(name="Sales Order Item", child=1, fields=[F("product", "Link", options="Product", reqd=1, in_list_view=1), F("quantity", "Float", in_list_view=1),
         F("uom", "Link", options="UOM", read_only=1), F("rate", "Currency", in_list_view=1), F("amount", "Currency", **RO),
         F("dispatched_qty", "Float", **RO), F("pending_qty", "Float", **RO)]),
    dict(name="Dispatch", autoname="format:DSP-{#####}", tx=1, perms=P(full=(STORE,), read=(SALES,)), fields=[
        F("sales_order", "Link", options="Sales Order", reqd=1, in_list_view=1), F("customer", "Link", options="Customer", read_only=1),
        F("dispatch_date", "Date"), F("items", "Table", options="Dispatch Item"), F("remarks", "Small Text"), *DONE]),
    dict(name="Dispatch Item", child=1, fields=[F("order_item", "Data"), F("product", "Link", options="Product", in_list_view=1),
         F("ordered_qty", "Float", **RO), F("already_dispatched", "Float", **RO), F("quantity", "Float", in_list_view=1), F("unit_cost", "Currency", **RO)]),
    dict(name="Stock Ledger Entry", autoname="hash", perms=[{"role": r, "read": 1} for r in ("System Manager", ADMIN, STORE, PROD)], fields=[
        F("product", "Link", options="Product", in_list_view=1), F("stage", "Select", options=STAGES, in_list_view=1),
        F("posting_datetime", "Datetime"), F("qty_in", "Float"), F("qty_out", "Float"), F("unit_price", "Currency"), F("value", "Currency"),
        F("reference_doctype", "Link", options="DocType"), F("reference_name", "Dynamic Link", options="reference_doctype"),
        F("is_reversal", "Check"), F("is_reversed", "Check")]),
    dict(name="Inventory", autoname="format:{product}-{stage}", perms=[{"role": r, "read": 1} for r in ("System Manager", ADMIN, STORE, PROD)], fields=[
        F("product", "Link", options="Product", reqd=1, in_list_view=1), F("stage", "Select", options=STAGES, reqd=1, in_list_view=1),
        F("stock", "Float", in_list_view=1), F("total_amount", "Currency"), F("unit_price", "Currency", in_list_view=1)]),
    dict(name="Master Version", single=1, perms=[{"role": "System Manager", "read": 1, "write": 1}], fields=[F("versions", "Code", options="JSON")]),
]

for d in DT:
    folder = d["name"].lower().replace(" ", "_")
    doc = {"doctype": "DocType", "name": d["name"], "module": "Clssurya", "engine": "InnoDB", "custom": 0,
           "istable": 1 if d.get("child") else 0, "issingle": 1 if d.get("single") else 0, "editable_grid": 1 if d.get("child") else 0,
           "track_changes": 1 if d.get("tx") else 0, "sort_field": "modified", "sort_order": "DESC",
           "fields": d["fields"], "field_order": [f["fieldname"] for f in d["fields"]],
           "permissions": [] if d.get("child") else d["perms"]}
    if d.get("autoname"):
        doc["autoname"] = d["autoname"]
    os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
    with open(os.path.join(ROOT, folder, folder + ".json"), "w") as fh:
        json.dump(doc, fh, indent=1)
print(len(DT), "DocTypes written")
