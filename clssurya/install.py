import frappe

from clssurya.constants import ROLES


def ensure_roles():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
                ignore_permissions=True
            )


def check_name_collisions():
    """Run BEFORE install-app:
    bench --site clssurya.local execute clssurya.install.check_name_collisions
    """
    import json
    import os

    base = os.path.join(os.path.dirname(__file__), "clssurya", "doctype")
    clashes = []
    for folder in sorted(os.listdir(base)):
        f = os.path.join(base, folder, folder + ".json")
        if os.path.exists(f):
            name = json.load(open(f))["name"]
            module = frappe.db.get_value("DocType", name, "module")
            if module and module != "Clssurya":
                clashes.append((name, module))
    print("Name collisions with Frappe core:", clashes or "none")
    return clashes
