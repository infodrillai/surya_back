import json

import frappe


def get_versions():
    raw = frappe.db.get_single_value("Master Version", "versions")
    return json.loads(raw) if raw else {}


def bump(doc, method=None):
    """doc_events hook for every master: increment the counter and tell the React cache."""
    versions = get_versions()
    versions[doc.doctype] = int(versions.get(doc.doctype, 0)) + 1
    frappe.db.set_single_value("Master Version", "versions", json.dumps(versions))
    frappe.publish_realtime(
        "masters_changed",
        {"doctype": doc.doctype, "version": versions[doc.doctype]},
        after_commit=True,
    )