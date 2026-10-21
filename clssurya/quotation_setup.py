import frappe

def add_hidden_fields_to_quotation():
    """Add hidden fields to Quotation doctype (if not already present)."""
    hidden_fields = [
        "status",
        "version",
        "previous_version",
        "cgst",
        "sgst",
        "igst",
        "discount",
        "discount_amount",
        "tax",
        "tax_amount",
    ]
    qt = frappe.get_doc("DocType", "Quotation")
    existing = {f.fieldname for f in qt.fields}
    for fieldname in hidden_fields:
        if fieldname not in existing:
            qt.append(
                "fields",
                {
                    "fieldname": fieldname,
                    "label": fieldname.replace('_', ' ').title(),
                    "fieldtype": "Float" if fieldname.endswith('_amount') or fieldname in ["cgst", "sgst", "igst", "discount", "tax"] else "Data",
                    "hidden": 1,
                    "read_only": 1,
                },
            )
    qt.save()
    frappe.db.commit()

def add_pr_field_to_quotation_item():
    """Add a read‑only `pr` Float field to Quotation Item doctype."""
    it = frappe.get_doc("DocType", "Quotation Item")
    if not any(f.fieldname == "pr" for f in it.fields):
        it.append(
            "fields",
            {
                "fieldname": "pr",
                "label": "PR (%)",
                "fieldtype": "Float",
                "read_only": 1,
                "precision": 2,
            },
        )
        it.save()
        frappe.db.commit()

def create_quotation_version_doctype():
    """Create a lightweight custom DocType to store quotation snapshots.
    The DocType is created only once (if it does not exist)."""
    if frappe.db.exists("DocType", "Quotation Version"):
        return
    qt = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Quotation Version",
            "module": "Clssurya",
            "custom": 1,
            "document_type": "Document",
            "is_submittable": 0,
            "istable": 0,
            "title_field": "quotation",
            "fields": [
                {
                    "fieldname": "quotation",
                    "label": "Quotation",
                    "fieldtype": "Link",
                    "options": "Quotation",
                    "reqd": 1,
                },
                {
                    "fieldname": "version_no",
                    "label": "Version No",
                    "fieldtype": "Int",
                    "reqd": 1,
                },
                {
                    "fieldname": "status",
                    "label": "Status",
                    "fieldtype": "Select",
                    "options": "Draft\nFinal\nRejected",
                    "default": "Draft",
                    "reqd": 1,
                },
                {
                    "fieldname": "snapshot",
                    "label": "Snapshot",
                    "fieldtype": "Code",
                    "options": "JSON",
                    "reqd": 1,
                },

            ],
        }
    )
    qt.insert()
    frappe.db.commit()

def apply():
    """Entry point to run from bench console or bench execute.
    Adds hidden fields, PR field, and creates Quotation Version DocType."""
    add_hidden_fields_to_quotation()
    add_pr_field_to_quotation_item()
    create_quotation_version_doctype()
    frappe.msgprint("✅ Custom quotation fields and Quotation Version DocType added.")

if __name__ == "__main__":
    apply()
