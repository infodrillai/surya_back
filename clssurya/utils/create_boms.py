import csv
import io
import re
import frappe
from clssurya.utils.versions import bump

CSV_TEXT = """CODE,Decription,Allu.,P. U,Moca,Bonding,Chemical,Allu. Oxide,2020-E,Total Amt Prodution,Rejection Coast 10%,TOTAL PRODUCTION COAST,LABOUR EXP,Electricity,CNC REPARING AND TOOLING COAST,TOTAL COAST,ADMIN EXP,TOTAL MFG COAST,,RAW MATERIAL,RAM PER KGPRICE
SAI021,Shuttle Roller P,27.13/60gm,11.16/24gm,1.75/4 gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,45.99,4.599,50.589,11.00,3.55,5.00,70.14,5,75.05,,ALUMINIUM,450
SAI021,Shutter Roller P OMEGA,27.13/60gm,11.16/24gm,1.75/4 gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,45.99,4.599,50.589,11.00,3.55,5.00,70.14,5,75.05,,PU ,466
SAI026,Shuttle Roller P CASTING,26,8.92/19.167m,1.67/3.83gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,42.54,4.254,46.794,11.00,3.55,5.00,66.34,5,70.99,,MOCA,438
SCI026,Shutter Roller P OMEGA  CASTING,26,8.92/19.167m,1.67/3.83gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,42.54,4.254,46.794,11.00,3.55,5.00,66.34,5,70.99,,2020 -E,2015
SAI025,SHUTTLE ROLLER OMEGA 52MM,40.50/13.950,10.71/23gm,1.97/4.50 gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,59.13,5.913,65.043,11.00,3.55,5.00,84.59,6,90.51,,Bonding,3065
SCI026,SHUTTLE ROLLER OMEGA 52MM CASTING,26,10.71/23gm,1.97/4.50 gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,44.63,4.463,49.093,11.00,3.55,5.00,68.64,5,73.45,,Chemical,225
SAI031,SHUTTLE ROLLER 6200,28.87/64gm,9.32/20 gm,1.75/4 gmgm,4.92/1.56,1.20/4.99,0.60/1.20,0.35/18gm,47.01,4.701,51.711,11.00,3.55,5.00,71.26,5,76.25,,OXIDE,59
SAI001,Excentric Wheel 45x28x19,18/40gm,6.99/15gm,1.31/3gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,32.25,3.23,35.48,11.00,3.55,5.00,55.03,4,58.88,,,
SAI002,Excentric Wheel 50mm,18/40gm,11.65/25gm,2.19/5gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,37.79,3.78,41.57,11.00,3.55,5.00,61.12,4,65.40,,,
SAI007,Excentric Wheel 52x28x19 ,25.60/56gm,9.78/21gm,2.19/5gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,43.52,4.35,47.87,11.00,3.55,5.00,67.42,5,72.14,,,
SAI003,Ropal Pulley  40x28x18,9.47/21gm,4.66/10g.m,1/2.50gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,20.63,2.06,22.69,11.00,3.55,5.00,42.24,3,45.20,,,
SAI004,Ropal Pulley / Cam Roller 45x28x18,18/40gm,6.99/15gm,1.31/3gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,32.25,3.23,35.48,11.00,3.55,5.00,55.03,4,58.88,,,
SAI011,Shuttle Wheel P,27.13/60gm,6.99/15gm,1.31/3gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,41.38,4.138,45.518,11.00,3.55,5.00,65.07,5,69.62,,,
SAI012,Shuttle Wheel 45x28x17,18/40gm,6.99/15gm,1.31/3gm,4.10/1.30gm,1/4.16gm,0.50/1gm,0.35/18gm,32.25,3.23,35.48,11.00,3.55,5.00,55.03,4,58.88,,,
SAI041,"Chonchoid Roller-P / Chon. Rear 45x28,26x42",52.84/117gm,18.64/40gm,3.50/8gm,8.20/2.60 gm,2/8.32 gm,1/2gm,0.35/18gm,86.53,8.65,95.18,20.00,3.55,5.00,123.73,9,132.39,,,
SAI044,"Chonchoid Roller 609 45x24,24x40",40/88gm,17.70/38gm,3/7gm,8.20/2.60 gm,2/8.32 gm,1/2gm,0.35/18gm,72.85,7.29,80.14,20.00,3.55,5.00,108.69,8,116.29,,,
SAI043,"Chonchoid Roller 6001 45x28,28x34",28/63gm,15.84/34gm,3.66/7gm,7/2.2gm,1.70/7gm,0.85/3.40gm,0.35/18gm,57.40,5.74,63.14,20.00,3.55,5.00,91.69,6,98.11,,,
SCI047,CHONCHOID ROLLER CASTING,35,16.31/35gm,3.66/7gm,8.20/2.60 gm,2/8.32 gm,1/2gm,0.35/18gm,66.52,6.65,73.17,20.00,3.55,5.00,101.72,7,108.84,,,
SNI049,CHONCHOID ROLLER-P NY,35,15 N+7.92/17gm,1.75/4gm,8.20/2.60 gm,2/8.32 gm,1/2gm,0.35/18gm,71.72,7.17,78.89,20.00,3.55,5.00,107.44,8,114.96,,,
SCI047,CHONCHOID ROLLER AP,35,16.31/35gm,3.66/7gm,8.20/2.60 gm,2/8.32 gm,1/2gm,0.35/18gm,66.52,6.65,73.17,20.00,3.55,5.00,101.72,7,108.84,,,
SCI068,STOPPER ROLLER P CASTING,25.5,11.65/25gm,2.19/5gm,6.15/1.95gm,1.50/6.24gm,0.75/1.5gm,0.35/18gm,48.09,4.81,52.90,17.00,3.55,5.00,78.45,5,83.94,,,
SAI061,STOPPER ROLLER P ,36/80gm,13.04/28gm,2.62/6gm,6.15/1.95gm,1.50/6.24gm,0.75/1.5gm,0.35/18gm,60.41,6.04,66.45,17.00,3.55,5.00,92.00,6,98.44,,,
SAI064,STOPPER ROLLER 609,30/67gm,13.04/28gm,2.62/6gm,6.15/1.95gm,1.50/6.24gm,0.75/1.5gm,0.35/18gm,54.41,5.44,59.85,17.00,3.55,5.00,85.40,6,91.38,,,
SAI065,STOPPER ROLLER 6001,24.75/55gm,13.04/28gm,2.62/6gm,6.15/1.95gm,1.50/6.24gm,0.75/1.5gm,0.35/18gm,49.31,4.93,54.24,17.00,3.55,5.00,79.79,6,85.38,,,
SAI082,DRIVING ROLL ALU. BIG,94.66/210gm,11.18/24gm,2.19/5gm,8.20/2.60gm,2/8.32,1/2gm,0.35/18gm,119.58,11.96,131.54,20.00,3.55,5.00,160.09,11,171.29,,,
SAI083,DRIVING ROLL ALU. SMALL,67.33/150gm,11.18/24gm,2.19/5gm,6.15/1.95gm,1.50/6.24gm,0.75/1.50,0.35/18gm,88.70,8.87,97.57,20.00,3.55,5.00,126.12,9,134.95,,,
SNI087,PUSHER WHEEL NIPU,20,13.51/29gm,3.06/7gm,8.20/2.60gm,2/8.32,1/2gm,0.35/18gm,48.12,4.81,52.93,11.00,3.55,5.00,72.48,5,77.56,,,
"""

# Mapping each CSV row to product codes
ROW_MAPPINGS = [
    # (row_index, sep_code, sai_code)
    (0, "SEP021", "SAI021"),
    (1, "SEP022", "SAI021-OMEGA"),
    (2, "SEP026", "SAI026"),
    (3, "SEP027", "SCI026-OMEGA"),
    (4, "SEP025", "SAI025"),
    (5, "SEP029", "SCI026-52"),
    (6, "SEP031", "SAI031"),
    (7, "SEP001", "SAI001"),
    (8, "SEP002", "SAI002"),
    (9, "SEP007", "SAI007"),
    (10, "SEP003", "SAI003"),
    (11, "SEP004", "SAI004"),
    (12, "SEP011", "SAI011"),
    (13, "SEP012", "SAI012"),
    (14, "SEP041", "SAI041"),
    (15, "SEP044", "SAI044"),
    (16, "SEP043", "SAI043"),
    (17, "SEP047", "SCI047"),
    (18, "SEP048", "SNI049"),
    (19, "SEP042", "SCI047-AP"),
    (20, "SEP068", "SCI068"),
    (21, "SEP061", "SAI061"),
    (22, "SEP065", "SAI064"),
    (23, "SEP064", "SAI065"),
    (24, "SEP082", "SAI082"),
    (25, "SEP083", "SAI083"),
    (26, "SEP087", "SNI087"),
]

RATES = {
    'ALM': 450.0,
    'PU': 466.0,
    'MOCA': 438.0,
    'BOND': 3065.0,
    'CHEM': 225.0,
    'OXIDE': 59.0,
    '2020E': 2015.0,
}

def extract_cost(cell):
    s = cell.strip()
    if not s:
        return 0.0
    if "/" in s:
        part = s.split('/')[0].strip()
        if "+" in part:
            parts = part.split('+')
            return sum(float(re.search(r'[\d\.]+', p).group(0)) for p in parts)
        return float(re.search(r'[\d\.]+', part).group(0))
    m = re.search(r'[\d\.]+', s)
    return float(m.group(0)) if m else 0.0

def ensure_masters():
    # 1. Raw Materials
    raw_materials = [
        ("ALM", "Aluminium", 0),
        ("SCP", "Scrap", 1),
        ("RAW-PU", "Polyurethane (PU)", 0),
        ("RAW-MOCA", "MOCA Curing Agent", 0),
        ("RAW-BOND", "Bonding Agent", 0),
        ("RAW-CHEM", "Chemical Additive", 0),
        ("RAW-OXIDE", "Aluminium Oxide", 0),
        ("RAW-2020E", "2020-E Stabilizer", 0),
    ]
    for code, name, is_scrap in raw_materials:
        if not frappe.db.exists("Product", code):
            doc = frappe.get_doc({
                "doctype": "Product",
                "product_code": code,
                "product_name": name,
                "product_type": "Raw",
                "total_steps": 0,
                "uom": "KG",
                "is_scrap": is_scrap,
                "allow_negative_stock": 0,
            })
            doc.insert(ignore_permissions=True)
            print(f"Created Raw Material: {code} - {name}")

    # 2. Charges
    charges = [
        "Labour Expense",
        "Electricity",
        "CNC Repairing and Tooling",
        "Admin Expense",
    ]
    for ch in charges:
        if not frappe.db.exists("Charge", ch):
            doc = frappe.get_doc({
                "doctype": "Charge",
                "charge_name": ch,
            })
            doc.insert(ignore_permissions=True)
            print(f"Created Charge: {ch}")

    # 3. Processes
    processes = [
        "Insert Machining",
        "PU Coating & Molding",
        "Finishing & Assembly",
    ]
    for pr in processes:
        if not frappe.db.exists("Process", pr):
            doc = frappe.get_doc({
                "doctype": "Process",
                "process_name": pr,
            })
            doc.insert(ignore_permissions=True)
            print(f"Created Process: {pr}")

def build_bom_data(row):
    c_alm = extract_cost(row['Allu.'])
    c_pu = extract_cost(row['P. U'])
    c_moca = extract_cost(row['Moca'])
    c_bond = extract_cost(row['Bonding'])
    c_chem = extract_cost(row['Chemical'])
    c_oxide = extract_cost(row['Allu. Oxide'])
    c_e2020 = extract_cost(row['2020-E'])

    labour = float(row['LABOUR EXP'] or 0)
    elec = float(row['Electricity'] or 0)
    cnc = float(row['CNC REPARING AND TOOLING COAST'] or 0)
    admin = float(row['ADMIN EXP'] or 0)

    # Utilization in KG
    u_alm = max(round(c_alm / RATES['ALM'], 6), 0.000001)
    u_pu = max(round(c_pu / RATES['PU'], 6), 0.000001)
    u_moca = max(round(c_moca / RATES['MOCA'], 6), 0.000001)
    u_bond = max(round(c_bond / RATES['BOND'], 6), 0.000001)
    u_chem = max(round(c_chem / RATES['CHEM'], 6), 0.000001)
    u_oxide = max(round(c_oxide / RATES['OXIDE'], 6), 0.000001)
    u_e2020 = max(round(c_e2020 / RATES['2020E'], 6), 0.000001)

    stage1_items = [
        {
            "process": "Insert Machining",
            "product": "ALM",
            "per_unit_utilization": u_alm,
            "wastage_product": "SCP",
        }
    ]

    stage2_items = [
        {"process": "PU Coating & Molding", "product": "RAW-PU", "per_unit_utilization": u_pu},
        {"process": "PU Coating & Molding", "product": "RAW-MOCA", "per_unit_utilization": u_moca},
        {"process": "PU Coating & Molding", "product": "RAW-BOND", "per_unit_utilization": u_bond},
        {"process": "PU Coating & Molding", "product": "RAW-CHEM", "per_unit_utilization": u_chem},
        {"process": "PU Coating & Molding", "product": "RAW-OXIDE", "per_unit_utilization": u_oxide},
        {"process": "PU Coating & Molding", "product": "RAW-2020E", "per_unit_utilization": u_e2020},
    ]

    stage3_charges = [
        {"charge": "Labour Expense", "per_unit_price": labour},
        {"charge": "Electricity", "per_unit_price": elec},
        {"charge": "CNC Repairing and Tooling", "per_unit_price": cnc},
        {"charge": "Admin Expense", "per_unit_price": admin},
    ]

    return stage1_items, stage2_items, stage3_charges

def save_bom_for_product(prod_code, stage1, stage2, stage3):
    if not frappe.db.exists("Product", prod_code):
        print(f"Product {prod_code} does not exist, skipping BOM.")
        return False

    # Check if BOM exists
    if frappe.db.exists("BOM", prod_code):
        bom_doc = frappe.get_doc("BOM", prod_code)
        bom_doc.set("stage1_items", [])
        bom_doc.set("stage2_items", [])
        bom_doc.set("stage3_charges", [])
        for row in stage1:
            bom_doc.append("stage1_items", row)
        for row in stage2:
            bom_doc.append("stage2_items", row)
        for row in stage3:
            bom_doc.append("stage3_charges", row)
        bom_doc.save(ignore_permissions=True)
        print(f"Updated BOM for {prod_code}")
    else:
        bom_doc = frappe.get_doc({
            "doctype": "BOM",
            "product": prod_code,
            "total_steps": 3,
            "stage1_items": stage1,
            "stage2_items": stage2,
            "stage3_charges": stage3,
        })
        bom_doc.insert(ignore_permissions=True)
        print(f"Created BOM for {prod_code}")
    return True

def run():
    ensure_masters()
    rows = list(csv.DictReader(io.StringIO(CSV_TEXT.strip())))
    
    boms_created = 0

    for idx, sep_code, sai_code in ROW_MAPPINGS:
        row = rows[idx]
        desc = row['Decription'].strip()
        stage1, stage2, stage3 = build_bom_data(row)

        # 1. Save BOM for SEP catalog code
        if frappe.db.exists("Product", sep_code):
            # Ensure total_steps = 3 and Finished
            p = frappe.get_doc("Product", sep_code)
            if p.product_type == "Raw" or p.total_steps != 3:
                p.product_type = "Finished"
                p.total_steps = 3
                p.save(ignore_permissions=True)
            save_bom_for_product(sep_code, stage1, stage2, stage3)
            boms_created += 1

        # 2. Also ensure SAI product exists and save BOM for it
        if not frappe.db.exists("Product", sai_code):
            doc = frappe.get_doc({
                "doctype": "Product",
                "product_code": sai_code,
                "product_name": desc,
                "product_type": "Finished",
                "total_steps": 3,
                "uom": "QTY",
                "allow_negative_stock": 0,
                "is_scrap": 0,
            })
            doc.insert(ignore_permissions=True)
            print(f"Created product {sai_code}: {desc}")
        save_bom_for_product(sai_code, stage1, stage2, stage3)
        boms_created += 1

    frappe.db.commit()
    print(f"\nAll done! Successfully configured BOMs for {boms_created} products.")

    # Bump Master Version for BOM and Product
    dummy_bom = frappe.get_doc("BOM", ROW_MAPPINGS[0][1])
    bump(dummy_bom)
    dummy_prod = frappe.get_doc("Product", ROW_MAPPINGS[0][1])
    bump(dummy_prod)
    frappe.db.commit()
    print("Master versions bumped for BOM and Product.")

