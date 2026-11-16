from clssurya.constants import MASTERS

app_name = "clssurya"
app_title = "CL Surya"
app_publisher = "Dilip"
app_description = "CL Surya ERP"
app_email = "dilip@example.com"
app_license = "MIT"

before_install = "clssurya.install.ensure_roles"
after_install = ["clssurya.patches.v1_0.load_initial_masters_and_boms.execute"]
after_migrate = [
    "clssurya.install.ensure_roles",
    "clssurya.patches.v1_0.load_initial_masters_and_boms.execute",
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

# Attach Sales Person auto-assignment and validation hooks
for dt in ("Quotation", "Sales Order", "Customer"):
    if dt not in doc_events:
        doc_events[dt] = {}
    doc_events[dt]["validate"] = "clssurya.utils.sales_person.validate_sales_person_doc"

website_route_rules = [
    {"from_route": "/surya/<path:app_path>", "to_route": "surya"},
]
