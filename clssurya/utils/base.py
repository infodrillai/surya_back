import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from clssurya.constants import ADMIN_ROLES
from clssurya.utils import stock_service


def is_admin(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(ADMIN_ROLES & set(frappe.get_roles(user)))


def require_admin():
    if not is_admin():
        frappe.throw(_("Only an Admin can do this."), frappe.PermissionError)


class CompletableDocument(Document):
    """Purchase Entry, Stage batches and Dispatch.

    Save = store + recalculate (no stock effect). complete() posts stock and sets the flag.
    The flag fields are only ever changed by complete()/reopen() through db_set.
    """

    # ---- hooks for subclasses -------------------------------------------------
    def calculate(self):
        pass

    def validate_doc(self):
        pass

    def stock_entries(self):
        return []

    def before_complete(self):
        pass

    def after_complete(self):
        pass

    def before_reopen(self):
        pass

    def after_reopen(self):
        pass

    # ---- locking ---------------------------------------------------------------
    def validate(self):
        before = self.get_doc_before_save()
        if self.is_new() or not before:
            self.is_completed, self.completed_on, self.completed_by = 0, None, None
        else:
            if cint(before.is_completed):
                frappe.throw(_("{0} {1} is completed and locked. An Admin must reopen it first.").format(self.doctype, self.name))
            # flag fields can never be changed through a normal save / API edit
            self.is_completed, self.completed_on, self.completed_by = 0, None, None
        self.calculate()
        self.validate_doc()

    def on_trash(self):
        if cint(self.is_completed):
            frappe.throw(_("A completed document cannot be deleted. Reopen it first."))

    # ---- actions ---------------------------------------------------------------
    def complete(self):
        self.check_permission("write")
        if cint(self.is_completed):
            frappe.throw(_("Already completed."))
        self.save()  # recalculates with the latest inventory prices
        self.before_complete()
        stock_service.post(self.stock_entries(), self.doctype, self.name)
        self.db_set({"is_completed": 1, "completed_on": now_datetime(), "completed_by": frappe.session.user})
        self.after_complete()
        return self.name

    def reopen(self):
        require_admin()
        if not cint(self.is_completed):
            frappe.throw(_("Only completed documents can be reopened."))
        self.before_reopen()
        stock_service.reverse(self.doctype, self.name)
        self.db_set({"is_completed": 0, "completed_on": None, "completed_by": None})
        self.after_reopen()
        return self.name
