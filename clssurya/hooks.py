from clssurya.constants import MASTERS

app_name = "clssurya"
app_title = "CL Surya"
app_publisher = "Dilip"
app_description = "CL Surya ERP"
app_email = "dilip@example.com"
app_license = "MIT"

before_install = "clssurya.install.ensure_roles"
after_migrate = ["clssurya.install.ensure_roles"]

# Every master bumps its version counter and notifies the React cache.
doc_events = {
    dt: {
        "after_insert": "clssurya.utils.versions.bump",
        "on_update": "clssurya.utils.versions.bump",
        "on_trash": "clssurya.utils.versions.bump",
    }
    for dt in MASTERS
}
