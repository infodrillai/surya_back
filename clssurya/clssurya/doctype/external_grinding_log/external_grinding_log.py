import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class ExternalGrindingLog(Document):
    def validate(self):
        self.entry_type = self.entry_type or "Outward"

        if self.entry_type == "Outward":
            self.validate_outward()
        elif self.entry_type == "Inward":
            self.validate_inward()

    def validate_outward(self):
        sent = flt(self.sent_qty)
        if sent <= 0:
            frappe.throw(_("Quantity Sent must be greater than zero."))

        if not self.outward_date:
            self.outward_date = nowdate()

        returned = flt(self.returned_qty)
        self.pending_qty = max(0.0, sent - returned)

        if not self.grinding_status or self.grinding_status not in ("Dispatched", "Partially Received", "Completed", "Cancelled"):
            if returned >= sent and sent > 0:
                self.grinding_status = "Completed"
            elif returned > 0:
                self.grinding_status = "Partially Received"
            else:
                self.grinding_status = "Dispatched"

    def validate_inward(self):
        if not self.outward_entry:
            frappe.throw(_("Related Outward Entry is required for an Inward record."))

        outward = frappe.get_doc("External Grinding Log", self.outward_entry)
        if outward.entry_type and outward.entry_type != "Outward":
            frappe.throw(_("Selected document {0} is not an Outward Entry.").format(self.outward_entry))

        # Auto-fetch details from Outward entry if not set
        if not self.job_reference:
            self.job_reference = outward.job_reference or outward.name
        if not self.product:
            self.product = outward.product
        if not self.vendor:
            self.vendor = outward.vendor
        if not self.uom:
            self.uom = outward.uom or "PCS"
        if not self.machine and outward.machine:
            self.machine = outward.machine
        if not self.employee and outward.employee:
            self.employee = outward.employee
        if not self.shift and outward.shift:
            self.shift = outward.shift
        if not self.process and outward.process:
            self.process = outward.process
        if not self.batch_no and outward.batch_no:
            self.batch_no = outward.batch_no

        received = flt(self.received_qty) or flt(self.returned_qty)
        if received <= 0:
            frappe.throw(_("Received Quantity must be greater than zero."))
        self.received_qty = received
        self.returned_qty = received

        accepted = flt(self.accepted_qty)
        rejected = flt(self.rejected_qty)

        if accepted < 0 or rejected < 0:
            frappe.throw(_("Accepted and Rejected quantities cannot be negative."))

        if (accepted + rejected) > (received + 1e-9):
            frappe.throw(
                _("Accepted Quantity ({0}) + Rejected Quantity ({1}) cannot exceed Received Quantity ({2}).").format(
                    accepted, rejected, received
                )
            )

        if rejected > 0 and not self.rejection_reason:
            frappe.throw(_("Rejection Reason is required when Rejected Quantity is greater than zero."))

        if not self.inward_date:
            self.inward_date = nowdate()

        # Check total received against outward dispatched quantity
        prev_received = frappe.db.sql("""
            SELECT COALESCE(SUM(COALESCE(received_qty, returned_qty, 0)), 0)
            FROM `tabExternal Grinding Log`
            WHERE outward_entry = %s AND name != %s AND docstatus < 2
        """, (self.outward_entry, self.name or ""))
        prior = flt(prev_received[0][0]) if prev_received else 0.0

        outward_sent = flt(outward.sent_qty)
        remaining = max(0.0, outward_sent - prior)

        if received > (remaining + 1e-9):
            frappe.throw(
                _("Received Quantity ({0}) exceeds remaining pending quantity ({1}) of Outward Entry {2}.").format(
                    received, remaining, self.outward_entry
                )
            )

        self.pending_qty = max(0.0, remaining - received)
        self.grinding_status = "Completed" if self.pending_qty <= 0 else "Partially Received"

    def on_update(self):
        if self.entry_type == "Inward" and self.outward_entry:
            sync_outward_entry_totals(self.outward_entry)

    def on_trash(self):
        if self.entry_type == "Inward" and self.outward_entry:
            sync_outward_entry_totals(self.outward_entry, exclude_name=self.name)


def sync_outward_entry_totals(outward_name, exclude_name=None):
    """Transaction-safe rollup of cumulative inward receipts to the parent outward entry."""
    if not outward_name or not frappe.db.exists("External Grinding Log", outward_name):
        return

    exclude_clause = "AND name != %(exclude)s" if exclude_name else ""
    params = {"outward": outward_name, "exclude": exclude_name}

    res = frappe.db.sql(f"""
        SELECT
            COALESCE(SUM(COALESCE(received_qty, returned_qty, 0)), 0) AS total_received,
            COALESCE(SUM(COALESCE(accepted_qty, 0)), 0) AS total_accepted,
            COALESCE(SUM(COALESCE(rejected_qty, 0)), 0) AS total_rejected
        FROM `tabExternal Grinding Log`
        WHERE outward_entry = %(outward)s AND docstatus < 2 {exclude_clause}
    """, params, as_dict=True)

    tot_received = flt(res[0].total_received) if res else 0.0
    tot_accepted = flt(res[0].total_accepted) if res else 0.0
    tot_rejected = flt(res[0].total_rejected) if res else 0.0

    sent = flt(frappe.db.get_value("External Grinding Log", outward_name, "sent_qty"))
    pending = max(0.0, sent - tot_received)

    if pending <= 0 and tot_received > 0:
        status = "Completed"
    elif tot_received > 0:
        status = "Partially Received"
    else:
        status = "Dispatched"

    frappe.db.set_value(
        "External Grinding Log",
        outward_name,
        {
            "returned_qty": tot_received,
            "received_qty": tot_received,
            "accepted_qty": tot_accepted,
            "rejected_qty": tot_rejected,
            "pending_qty": pending,
            "grinding_status": status,
        },
        update_modified=False,
    )

