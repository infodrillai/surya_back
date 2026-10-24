import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate
from clssurya.utils import stock_service

EPS = 1e-6

class GoodsReceipt(Document):
    def before_insert(self):
        if not self.status:
            self.status = "Draft"

    def validate(self):
        if self.is_new() and not self.status:
            self.status = "Draft" 
        if not self.purchase_order:
            frappe.throw(_("Purchase Order reference is required."))
        po = frappe.get_doc("Purchase Entry", self.purchase_order)
        self.vendor = po.vendor
        if not self.posting_date:
            self.posting_date = nowdate()
        if not self.items:
            frappe.throw(_("Add at least one item to receive."))
        for r in self.items:
            if flt(r.received_qty) <= 0:
                frappe.throw(_("Row {0}: Received quantity must be greater than 0.").format(r.idx))
            if not r.product_name:
                r.product_name = frappe.db.get_value("Product", r.product, "product_name") or r.product
            if not r.uom:
                r.uom = frappe.db.get_value("Product", r.product, "uom")
        self.total_qty = sum(flt(r.received_qty) for r in self.items)
        self.total_amount = sum(flt(r.received_qty) * flt(r.rate) for r in self.items)

    @frappe.whitelist()
    def confirm_receipt(self):
        self.check_permission("write")
        if self.status == "Confirmed":
            frappe.throw(_("Goods Receipt {0} is already confirmed.").format(self.name))
        if self.status == "Cancelled":
            frappe.throw(_("Cannot confirm a cancelled Goods Receipt."))

        # 1. Lock Purchase Order row to serialize concurrent receipts
        frappe.db.sql(
            "SELECT name FROM `tabPurchase Entry` WHERE name=%s FOR UPDATE",
            (self.purchase_order,),
        )
        po = frappe.get_doc("Purchase Entry", self.purchase_order)

        if po.status not in ("Ordered", "Partially Received"):
            frappe.throw(
                _("Cannot receive goods against Purchase Order {0} with status '{1}'. Must be Ordered or Partially Received.")
                .format(po.name, po.status)
            )

        # 2. Query all existing confirmed receipts for this PO excluding self
        confirmed_grs = frappe.get_all(
            "Goods Receipt",
            filters={"purchase_order": self.purchase_order, "status": "Confirmed", "name": ("!=", self.name)},
            pluck="name",
        )
        already_received_map = {}
        for gr_name in confirmed_grs:
            for row in frappe.get_doc("Goods Receipt", gr_name).items:
                already_received_map[row.purchase_order_item] = already_received_map.get(row.purchase_order_item, 0.0) + flt(row.received_qty)

        # 3. Validate line quantities against PO remaining
        po_items_by_id = {line.name: line for line in po.items}
        for item in self.items:
            po_line = po_items_by_id.get(item.purchase_order_item)
            if not po_line:
                # Try finding by product if item reference was not set
                po_line = next((l for l in po.items if l.product == item.product), None)
                if po_line:
                    item.purchase_order_item = po_line.name

            if not po_line:
                frappe.throw(_("Item {0} not found on Purchase Order {1}.").format(item.product, po.name))

            ordered = flt(po_line.quantity)
            already_rcv = already_received_map.get(po_line.name, 0.0)
            remaining = max(0.0, ordered - already_rcv)
            rcv_qty = flt(item.received_qty)

            if rcv_qty <= 0:
                frappe.throw(_("Quantity received for {0} must be greater than 0.").format(item.product))
            if rcv_qty > remaining + EPS:
                pname = frappe.db.get_value("Product", item.product, "product_name") or item.product
                frappe.throw(
                    _("Cannot receive {0} of {1}. Only {2} remaining (ordered {3}, previously received {4}).")
                    .format(flt(rcv_qty, 4), pname, flt(remaining, 4), flt(ordered, 4), flt(already_rcv, 4))
                )

            item.product_name = frappe.db.get_value("Product", item.product, "product_name") or item.product
            item.uom = po_line.uom or frappe.db.get_value("Product", item.product, "uom")
            item.rate = flt(po_line.rate)
            item.landed_rate = flt(po_line.landed_rate) if flt(po_line.landed_rate) else flt(po_line.rate)
            item.ordered_qty = ordered
            item.already_received_qty = already_rcv
            item.pending_qty = max(0.0, remaining - rcv_qty)
            item.amount = rcv_qty * flt(po_line.rate)

        # 4. Post stock entries via stock_service
        stock_entries = [
            {
                "product": item.product,
                "stage": "Raw",
                "qty": flt(item.received_qty),
                "unit_price": flt(item.landed_rate),
            }
            for item in self.items
        ]
        stock_service.post(stock_entries, "Goods Receipt", self.name)

        # 5. Update Purchase Order item received/pending quantities
        for line in po.items:
            current_rcv = sum(flt(i.received_qty) for i in self.items if i.purchase_order_item == line.name)
            tot_rcv_line = already_received_map.get(line.name, 0.0) + current_rcv
            tot_pending_line = max(0.0, flt(line.quantity) - tot_rcv_line)
            frappe.db.set_value(
                "Purchase Entry Item",
                line.name,
                {"received_qty": tot_rcv_line, "pending_qty": tot_pending_line},
                update_modified=False,
            )

        # 6. Update Purchase Order status and header totals
        po.reload()
        tot_ordered = sum(flt(l.quantity) for l in po.items)
        tot_received = sum(flt(l.received_qty) for l in po.items)
        tot_pending = max(0.0, tot_ordered - tot_received)

        all_received = all(flt(l.received_qty) >= flt(l.quantity) - EPS for l in po.items)
        any_received = any(flt(l.received_qty) > EPS for l in po.items)

        if all_received:
            po_status = "Received"
            is_completed = 1
        elif any_received:
            po_status = "Partially Received"
            is_completed = 0
        else:
            po_status = "Ordered"
            is_completed = 0

        po.db_set({
            "status": po_status,
            "total_ordered_qty": tot_ordered,
            "total_received_qty": tot_received,
            "total_pending_qty": tot_pending,
            "is_completed": is_completed,
        })

        # 7. Update self to Confirmed
        self.total_qty = sum(flt(i.received_qty) for i in self.items)
        self.total_amount = sum(flt(i.amount) for i in self.items)
        self.db_set({
            "status": "Confirmed",
            "total_qty": self.total_qty,
            "total_amount": self.total_amount,
            "confirmed_on": now_datetime(),
            "confirmed_by": frappe.session.user,
        })

        return {"name": self.name, "status": "Confirmed", "po_status": po_status}

    @frappe.whitelist()
    def cancel_receipt(self):
        self.check_permission("write")
        if self.status != "Confirmed":
            frappe.throw(_("Only confirmed goods receipts can be cancelled."))

        # 1. Lock Purchase Order row
        frappe.db.sql(
            "SELECT name FROM `tabPurchase Entry` WHERE name=%s FOR UPDATE",
            (self.purchase_order,),
        )
        po = frappe.get_doc("Purchase Entry", self.purchase_order)

        # 2. Reverse stock entries (stock_service.reverse raises if subsequent stock movements prevent reversal)
        stock_service.reverse("Goods Receipt", self.name)

        # 3. Restore PO item quantities
        for item in self.items:
            po_line = next((l for l in po.items if l.name == item.purchase_order_item), None)
            if not po_line:
                po_line = next((l for l in po.items if l.product == item.product), None)
            if po_line:
                new_rcv = max(0.0, flt(po_line.received_qty) - flt(item.received_qty))
                new_pending = max(0.0, flt(po_line.quantity) - new_rcv)
                frappe.db.set_value(
                    "Purchase Entry Item",
                    po_line.name,
                    {"received_qty": new_rcv, "pending_qty": new_pending},
                    update_modified=False,
                )

        # 4. Recalculate PO status
        po.reload()
        tot_ordered = sum(flt(l.quantity) for l in po.items)
        tot_received = sum(flt(l.received_qty) for l in po.items)
        tot_pending = max(0.0, tot_ordered - tot_received)

        all_received = all(flt(l.received_qty) >= flt(l.quantity) - EPS for l in po.items)
        any_received = any(flt(l.received_qty) > EPS for l in po.items)

        if all_received:
            po_status = "Received"
            is_completed = 1
        elif any_received:
            po_status = "Partially Received"
            is_completed = 0
        else:
            po_status = "Ordered"
            is_completed = 0

        po.db_set({
            "status": po_status,
            "total_ordered_qty": tot_ordered,
            "total_received_qty": tot_received,
            "total_pending_qty": tot_pending,
            "is_completed": is_completed,
        })

        # 5. Mark self Cancelled
        self.db_set({
            "status": "Cancelled",
            "cancelled_on": now_datetime(),
            "cancelled_by": frappe.session.user,
        })

        return {"name": self.name, "status": "Cancelled", "po_status": po_status}
