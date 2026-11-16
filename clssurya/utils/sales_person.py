import frappe
from frappe import _
from clssurya.utils.base import is_admin


def get_current_sales_person(user=None):
    """Returns the active Sales Person record linked to the given user (or session user)."""
    user = user or frappe.session.user
    if not user or user in ("Guest", "Administrator"):
        return None

    # Check by assigned_user first
    sp = frappe.db.get_value(
        "Sales Person",
        {"assigned_user": user},
        ["name", "sales_person_name", "employee_id", "email", "mobile_no", "status"],
        as_dict=True,
    )
    if not sp:
        # Fallback to email match
        sp = frappe.db.get_value(
            "Sales Person",
            {"email": user},
            ["name", "sales_person_name", "employee_id", "email", "mobile_no", "status"],
            as_dict=True,
        )

    return sp


def is_sales_person(user=None):
    """True if user has Sales Person or CS Sales role and is not an Admin."""
    user = user or frappe.session.user
    if is_admin(user):
        return False
    user_roles = set(frappe.get_roles(user))
    return bool(user_roles & {"Sales Person", "CS Sales"})


def get_quotation_permission_query_conditions(user):
    return _sales_person_query_condition(user, "Quotation")


def get_sales_order_permission_query_conditions(user):
    return _sales_person_query_condition(user, "Sales Order")


def get_customer_permission_query_conditions(user):
    return _sales_person_query_condition(user, "Customer")


def _sales_person_query_condition(user, doctype):
    if is_admin(user):
        return ""
    if is_sales_person(user):
        sp = get_current_sales_person(user)
        if sp and sp.get("status") == "Active":
            escaped_sp = frappe.db.escape(sp.name)
            # Sales person sees records assigned to them or records with no sales_person assigned yet
            return f"(`tab{doctype}`.sales_person = {escaped_sp})"
        # If user has sales person role but is inactive or unmapped, return impossible condition
        return "1=0"
    return ""


def validate_sales_person_doc(doc, method=None):
    """Validation hook for Customer, Quotation, and Sales Order."""
    user = frappe.session.user
    if user == "Administrator" or is_admin(user):
        return

    if is_sales_person(user):
        sp = get_current_sales_person(user)
        if not sp or sp.get("status") != "Active":
            frappe.throw(
                _("Your Sales Person profile is inactive or not assigned. Please contact the Administrator."),
                frappe.PermissionError,
            )

        # On creation, auto-assign
        if doc.is_new():
            doc.sales_person = sp.name
        else:
            # Prevent tampering with existing ownership
            before = doc.get_doc_before_save()
            if before and before.sales_person and before.sales_person != sp.name:
                frappe.throw(
                    _("You do not have permission to modify another Sales Person's document."),
                    frappe.PermissionError,
                )
            if before and before.sales_person and doc.sales_person != before.sales_person:
                frappe.throw(
                    _("You cannot reassign document ownership."),
                    frappe.PermissionError,
                )

        # Enforce Quotation / Sales Order status workflow limits for Sales Person
        if doc.doctype == "Quotation":
            before = doc.get_doc_before_save()
            if before and before.status in ("Accepted", "Superseded"):
                frappe.throw(_("Quotation {0} is {1} and cannot be modified. Revise it instead.").format(doc.name, before.status))
            # Sales person cannot directly approve or reject
            if doc.status == "Approved" and (not before or before.status != "Approved"):
                frappe.throw(_("Only an Administrator can approve quotations."), frappe.PermissionError)
            if doc.status == "Rejected" and (not before or before.status != "Rejected"):
                frappe.throw(_("Only an Administrator can reject quotations."), frappe.PermissionError)

        elif doc.doctype == "Sales Order":
            before = doc.get_doc_before_save()
            if doc.status in ("Approved", "Rejected", "Cancelled"):
                if not before or before.status != doc.status:
                    frappe.throw(_("Only an Administrator can change Sales Order status to {0}.").format(doc.status), frappe.PermissionError)
