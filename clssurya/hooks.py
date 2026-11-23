from clssurya.constants import MASTERS

app_name = "clssurya"
app_title = "CLS Surya"
app_publisher = "Dilip"
app_description = "CLS Surya ERP"
app_email = "dilip@example.com"
app_license = "MIT"

before_install = "clssurya.install.ensure_roles"
after_install = ["clssurya.patches.v1_0.load_initial_masters_and_boms.execute"]
after_migrate = [
    "clssurya.install.ensure_roles",
    "clssurya.patches.v1_0.load_initial_masters_and_boms.execute",
    "clssurya.utils.rejections.seed_rejection_reasons",
    "clssurya.utils.rejections.ensure_belt_batch_fields",
    "clssurya.utils.batch_tracking.ensure_belt_batch_tracking_fields",
]

# Permission Query Conditions for Sales Person row-level isolation
permission_query_conditions = {
    "Quotation": "clssurya.utils.sales_person.get_quotation_permission_query_conditions",
    "Sales Order": "clssurya.utils.sales_person.get_sales_order_permission_query_conditions",
    "Customer": "clssurya.utils.sales_person.get_customer_permission_query_conditions",
}

# Master version bumping and ownership validation
doc_events = {
    dt: {
        "after_insert": "clssurya.utils.versions.bump",
        "on_update": "clssurya.utils.versions.bump",
        "on_trash": "clssurya.utils.versions.bump",
    }
    for dt in MASTERS
}

# Central rejection records stay linked to their production transaction and are
# upserted after each save, so retries and edits never create duplicate rows.
for _dt in ("Stage 1 Batch", "Stage 2 Batch", "Stage 3 Batch", "CNC Machine Log",
            "Bonding Log", "Coating Log", "External Grinding Log"):
    doc_events.setdefault(_dt, {})["on_update"] = "clssurya.utils.rejections.sync_rejection_entry"
    doc_events[_dt]["after_insert"] = "clssurya.utils.rejections.sync_rejection_entry"
    doc_events[_dt]["before_save"] = "clssurya.utils.rejections.sync_legacy_operator"
    doc_events[_dt]["validate"] = "clssurya.utils.rejections.validate_active_references"
    doc_events[_dt]["on_trash"] = "clssurya.utils.rejections.clear_rejection_entry"
doc_events["Belt Batch"] = {
    "before_save": "clssurya.utils.rejections.sync_legacy_operator",
    "validate": "clssurya.utils.belt_batch.validate",
    "after_insert": "clssurya.utils.rejections.sync_rejection_entry",
    "on_update": "clssurya.utils.belt_batch.on_update",
    "on_trash": "clssurya.utils.belt_batch.on_trash",
}

# Attach Sales Person auto-assignment and validation hooks
for dt in ("Quotation", "Sales Order", "Customer"):
    if dt not in doc_events:
        doc_events[dt] = {}
    doc_events[dt]["validate"] = "clssurya.utils.sales_person.validate_sales_person_doc"

website_route_rules = [
    {"from_route": "/surya/<path:app_path>", "to_route": "surya"},
]
