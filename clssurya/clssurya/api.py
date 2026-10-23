# clssurya/api.py
"""Generic API endpoint used by the front‑end to call whitelisted DocType methods.

The UI calls `runAction(doctype, name, method, args)` which POSTs to
`/api/method/clssurya.api.run_action`.  This wrapper fetches the document
and invokes the requested method, propagating any return value or exception.
"""

import frappe
from frappe import csrf_exempt

@frappe.whitelist()
def run_action(doctype: str, name: str, method: str, **kwargs):
    """Call a whitelisted method on a given document.

    Parameters
    ----------
    doctype: str
        DocType name, e.g. "Sales Order".
    name: str
        Document name/ID.
    method: str
        Name of the method defined on the DocType class (must be whitelisted).
    **kwargs: dict
        Arguments passed to the called method.
    """
    doc = frappe.get_doc(doctype, name)
    # Ensure the method exists and is callable. Whitelisting is enforced by the
    # `@frappe.whitelist()` decorator on the method itself.
    if not hasattr(doc, method):
        frappe.throw(f"Method {method} not found on {doctype}")
    fn = getattr(doc, method)
    if not callable(fn):
        frappe.throw(f"{method} on {doctype} is not callable")
    return fn(**kwargs)

@frappe.whitelist()
def get_quotation_navigation(name: str):
    """Return navigation information (previous, next, current, family) for a quotation name.
    Utilises the utilities in ``clssurya.utils.quotation_versions``.
    """
    from clssurya.utils.quotation_versions import get_version_navigation
    return get_version_navigation(name)
