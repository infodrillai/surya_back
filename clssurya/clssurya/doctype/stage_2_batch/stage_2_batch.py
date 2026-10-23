from clssurya.utils.stage import StageBatch
import frappe


class Stage2Batch(StageBatch):
    STAGE = 2

    def on_trash(self):
        """Allow deletion of a Stage 2 batch while preserving the original
        stock entry price (without rejection)."""
        # Only Draft (0) or Cancelled (2) batches can be deleted
        if self.docstatus == 1:
            frappe.throw(_("Only Draft or Cancelled Stage 2 batches can be deleted."))

        # Reverse stock using the stored price without rejection
        original_price = frappe.utils.flt(self.unit_cost_without_rejection)
        for entry in self.stock_entries():
            frappe.db.set_value(
                "Stock Ledger Entry",
                {"voucher_no": self.name, "product": entry["product"]},
                "unit_price",
                original_price,
            )
        super().on_trash()
