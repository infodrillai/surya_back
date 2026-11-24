import os
import frappe

def create_belt_batch_doctype():
    os.chdir("/home/rutva_javiya/frappe-bench/sites")
    frappe.init("clssurya.local", sites_path="/home/rutva_javiya/frappe-bench/sites")
    frappe.connect()

    # 1. Create Child Table: Belt Batch Item
    if not frappe.db.exists("DocType", "Belt Batch Item"):
        print("Creating DocType 'Belt Batch Item'...")
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Belt Batch Item",
            "module": "Clssurya",
            "custom": 1,
            "istable": 1,
            "fields": [
                {"fieldname": "process", "label": "Process", "fieldtype": "Data", "read_only": 1, "in_list_view": 1},
                {"fieldname": "product", "label": "Product", "fieldtype": "Link", "options": "Product", "read_only": 1, "in_list_view": 1},
                {"fieldname": "calculation_type", "label": "Calc By", "fieldtype": "Select", "options": "Hole\nQuantity", "read_only": 1},
                {"fieldname": "ratio", "label": "Ratio", "fieldtype": "Float", "read_only": 1},
                {"fieldname": "per_unit_utilization", "label": "Per Unit", "fieldtype": "Float", "read_only": 1},
                {"fieldname": "total_utilization", "label": "Estimate", "fieldtype": "Float", "read_only": 1},
                {"fieldname": "actual_utilization", "label": "Actual Used", "fieldtype": "Float", "in_list_view": 1},
                {"fieldname": "unit_price", "label": "Unit Price", "fieldtype": "Currency", "read_only": 1},
                {"fieldname": "actual_amount", "label": "Actual Amount", "fieldtype": "Currency", "read_only": 1, "in_list_view": 1},
                {"fieldname": "extra_cost", "label": "Extra Cost", "fieldtype": "Currency"},
                {"fieldname": "is_carried_in", "label": "Is Carried In", "fieldtype": "Check", "default": "0"},
            ]
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        print("✓ Created 'Belt Batch Item'")
    else:
        print("✓ 'Belt Batch Item' already exists")

    # 2. Create Child Table: Belt Batch Charge
    if not frappe.db.exists("DocType", "Belt Batch Charge"):
        print("Creating DocType 'Belt Batch Charge'...")
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Belt Batch Charge",
            "module": "Clssurya",
            "custom": 1,
            "istable": 1,
            "fields": [
                {"fieldname": "charge", "label": "Charge", "fieldtype": "Link", "options": "Charge", "read_only": 1, "in_list_view": 1},
                {"fieldname": "per_unit_price", "label": "Per Unit", "fieldtype": "Currency", "in_list_view": 1},
                {"fieldname": "calculation_basis", "label": "Basis", "fieldtype": "Select", "options": "Per Piece\nPer Meter\nFixed", "default": "Per Piece", "in_list_view": 1},
                {"fieldname": "quantity", "label": "Quantity", "fieldtype": "Float"},
                {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "read_only": 1, "in_list_view": 1},
            ]
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        print("✓ Created 'Belt Batch Charge'")
    else:
        print("✓ 'Belt Batch Charge' already exists")

    # 3. Create Main DocType: Belt Batch
    if not frappe.db.exists("DocType", "Belt Batch"):
        print("Creating DocType 'Belt Batch'...")
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Belt Batch",
            "module": "Clssurya",
            "custom": 1,
            "is_submittable": 0,
            "autoname": "Prompt",
            "fields": [
                {"fieldname": "stage", "label": "Stage", "fieldtype": "Int", "reqd": 1, "in_list_view": 1},
                {"fieldname": "process_step", "label": "Process Step", "fieldtype": "Int"},
                {"fieldname": "current_process", "label": "Current Process", "fieldtype": "Data"},
                {"fieldname": "product", "label": "Product", "fieldtype": "Link", "options": "Product", "reqd": 1, "in_list_view": 1},
                {"fieldname": "belt_type", "label": "Belt Type", "fieldtype": "Data"},
                {"fieldname": "quantity", "label": "Quantity Produced", "fieldtype": "Float", "reqd": 1, "default": "100", "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "in_list_view": 1},
                {"fieldname": "size", "label": "Size", "fieldtype": "Float"},
                {"fieldname": "length", "label": "Length (mm)", "fieldtype": "Float"},
                {"fieldname": "width", "label": "Width (mm)", "fieldtype": "Float"},
                {"fieldname": "holes", "label": "Hole", "fieldtype": "Float"},
                {"fieldname": "roll_division_factor", "label": "Division Factor", "fieldtype": "Float"},
                {"fieldname": "roll_required", "label": "Roll Required (m)", "fieldtype": "Float"},
                {"fieldname": "roll_consumed", "label": "Roll Consumed (m)", "fieldtype": "Float"},
                {"fieldname": "remaining_roll", "label": "Remaining Roll (m)", "fieldtype": "Float"},
                {"fieldname": "wastage_qty", "label": "Wastage Qty", "fieldtype": "Float"},
                {"fieldname": "rejection_percent", "label": "Rejection %", "fieldtype": "Float", "default": "0"},
                {"fieldname": "rejection_amount", "label": "Rejection Amount", "fieldtype": "Currency", "read_only": 1},
                {"fieldname": "carried_cost", "label": "Carried Cost", "fieldtype": "Currency", "read_only": 1},
                {"fieldname": "added_cost", "label": "Added Cost", "fieldtype": "Currency", "read_only": 1},
                {"fieldname": "charge_total", "label": "Charge Total", "fieldtype": "Currency", "read_only": 1},
                {"fieldname": "batch_total", "label": "Batch Total", "fieldtype": "Currency", "read_only": 1, "in_list_view": 1},
                {"fieldname": "unit_cost", "label": "Unit Cost", "fieldtype": "Currency", "read_only": 1, "in_list_view": 1},
                {"fieldname": "is_completed", "label": "Is Completed", "fieldtype": "Check", "default": "0", "in_list_view": 1},
                {"fieldname": "remarks", "label": "Remarks", "fieldtype": "Small Text"},
                {"fieldname": "items_section", "label": "Items", "fieldtype": "Section Break"},
                {"fieldname": "items", "label": "Items", "fieldtype": "Table", "options": "Belt Batch Item"},
                {"fieldname": "charges_section", "label": "Charges", "fieldtype": "Section Break"},
                {"fieldname": "charges", "label": "Charges", "fieldtype": "Table", "options": "Belt Batch Charge"},
            ],
            "permissions": [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
                {"role": "Belt Operator", "read": 1, "write": 1, "create": 1},
                {"role": "All", "read": 1, "write": 1, "create": 1}
            ]
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        print("✓ Created 'Belt Batch'")
    else:
        print("✓ 'Belt Batch' already exists")

if __name__ == "__main__":
    create_belt_batch_doctype()

