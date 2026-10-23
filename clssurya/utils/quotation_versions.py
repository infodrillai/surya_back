import frappe
from frappe import _
from frappe.utils import cint

MAX_DEPTH = 500


def get_family_root(name):
    """Walk up parent_quotation until the first version is reached."""
    seen, current = set(), name
    while current and current not in seen and len(seen) < MAX_DEPTH:
        seen.add(current)
        parent = frappe.db.get_value("Quotation", current, "parent_quotation")
        if not parent:
            break
        current = parent
    return current


def get_family_members(name):
    """All quotation names in the same family (works for root-style and chain-style links)."""
    root = get_family_root(name)
    members, frontier = {root}, [root]
    while frontier and len(members) < MAX_DEPTH:
        children = frappe.get_all(
            "Quotation",
            filters={"parent_quotation": ["in", frontier], "name": ["not in", list(members)]},
            pluck="name",
        )
        members.update(children)
        frontier = children
    return list(members)


def get_latest_version(name):
    rows = frappe.get_all(
        "Quotation", filters={"name": ["in", get_family_members(name)]}, fields=["version"]
    )
    return max((cint(r.version) or 1 for r in rows), default=1)


def get_version_navigation(name):
    """Previous/next within the family, respecting the user's read permission."""
    if not frappe.has_permission("Quotation", "read", doc=name):
        raise frappe.PermissionError

    rows = frappe.get_list(
        "Quotation",
        filters={"name": ["in", get_family_members(name)]},
        fields=["name", "version", "status"],
        order_by="version asc, creation asc",
        limit_page_length=0,
    )
    idx = next((i for i, r in enumerate(rows) if r.name == name), None)
    if idx is None:
        raise frappe.PermissionError

    return {
        "current": rows[idx],
        "previous": rows[idx - 1].name if idx > 0 else None,
        "next": rows[idx + 1].name if idx < len(rows) - 1 else None,
        "family": rows,
    }