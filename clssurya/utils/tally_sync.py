import re
import datetime
import xml.etree.ElementTree as ET
import requests
import frappe
from frappe.utils import flt, now_datetime


GST_STATE_MAP = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh"
}


def normalize_url(url: str) -> str:
    if not url:
        return "http://localhost:9000"
    u = url.strip()
    if u.isdigit():
        return f"http://localhost:{u}"
    if not u.startswith("http://") and not u.startswith("https://"):
        u = f"http://{u}"
    return u.rstrip("/")


def build_company_list_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>List of Companies</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def build_ledger_list_xml(group_name: str = "Sundry Debtors", company_name: str = "") -> str:
    child_of_tag = ""
    trimmed_group = (group_name or "").strip()
    if trimmed_group and trimmed_group.lower() != "all":
        if trimmed_group.lower() == "sundry debtors":
            child_of_tag = "<CHILDOF>$$GroupSundryDebtors</CHILDOF>"
        elif trimmed_group.lower() == "sundry creditors":
            child_of_tag = "<CHILDOF>$$GroupSundryCreditors</CHILDOF>"
        else:
            child_of_tag = f'<CHILDOF>"{trimmed_group}"</CHILDOF>'

    current_company_tag = ""
    if company_name and company_name.strip():
        comp_clean = company_name.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        current_company_tag = f"<SVCURRENTCOMPANY>{comp_clean}</SVCURRENTCOMPANY>"

    return f"""<?xml version="1.0" encoding="utf-8"?>
<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>Ledger</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        {current_company_tag}
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="Ledger" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
            <TYPE>Ledger</TYPE>
            {child_of_tag}
            <FETCH>NAME,PARENT,ADDRESS,STATENAME,COUNTRYNAME,PINCODE,PARTYGSTIN,INCOMETAXNUMBER,EMAIL,LEDGERPHONE,LEDGERMOBILE,CONTACTPERSON,CLOSINGBALANCE,OPENINGBALANCE,DESCRIPTION,CREDITLIMIT,MAILINGNAME,BILLALLOCATIONS.*,ALLBILLALLOCATIONS.*</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def parse_safe_text(elem) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def parse_amount(val, raw_val=None):
    if raw_val is not None and raw_val != "":
        try:
            num = float(raw_val)
            btype = "Cr" if num < 0 else ("Dr" if num > 0 else "Zero")
            return abs(num), btype
        except (ValueError, TypeError):
            pass

    if isinstance(val, (int, float)):
        btype = "Cr" if val < 0 else ("Dr" if val > 0 else "Zero")
        return abs(float(val)), btype

    if not val or not isinstance(val, str):
        return 0.0, "Zero"

    s = val.strip()
    is_cr = "Cr" in s or s.startswith("-")
    is_dr = "Dr" in s

    clean_digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        amount = float(clean_digits) if clean_digits else 0.0
    except ValueError:
        amount = 0.0

    if is_cr:
        return amount, "Cr"
    elif is_dr or amount > 0:
        return amount, "Dr"
    return 0.0, "Zero"


def parse_tally_date(d_str: str):
    if not d_str:
        return None
    s = d_str.strip()
    if len(s) == 8 and s.isdigit():
        try:
            y = int(s[0:4])
            m = int(s[4:6])
            d = int(s[6:8])
            return datetime.date(y, m, d)
        except Exception:
            return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None


def calculate_ageing_from_ledger_elem(ledger_elem, closing_bal_num: float, opening_bal_num: float, company_name: str = ""):
    age = {
        "age_0_30": 0.0,
        "age_30_60": 0.0,
        "age_60_90": 0.0,
        "age_90_120": 0.0,
        "age_120_150": 0.0,
        "age_150_180": 0.0,
        "age_180_above": 0.0,
    }
    abs_closing = abs(closing_bal_num or 0.0)
    if abs_closing == 0:
        return age

    today = datetime.date.today()
    allocated_total = 0.0

    bill_elems = ledger_elem.findall(".//BILLALLOCATIONS") + ledger_elem.findall(".//ALLBILLALLOCATIONS")
    for b in bill_elems:
        b_date_elem = b.find("BILLDATE") or b.find("DATE")
        b_amt_elem = b.find("OPENINGBALANCE") or b.find("CLOSINGBALANCE") or b.find("AMOUNT")
        b_date_str = parse_safe_text(b_date_elem)
        b_date = parse_tally_date(b_date_str)
        b_amt_str = parse_safe_text(b_amt_elem)

        amt_val, _ = parse_amount(b_amt_str)
        if amt_val > 0:
            diff_days = (today - b_date).days if b_date else 181
            if diff_days <= 30:
                age["age_0_30"] += amt_val
            elif diff_days <= 60:
                age["age_30_60"] += amt_val
            elif diff_days <= 90:
                age["age_60_90"] += amt_val
            elif diff_days <= 120:
                age["age_90_120"] += amt_val
            elif diff_days <= 150:
                age["age_120_150"] += amt_val
            elif diff_days <= 180:
                age["age_150_180"] += amt_val
            else:
                age["age_180_above"] += amt_val
            allocated_total += amt_val

    unallocated = abs_closing - allocated_total
    if unallocated > 0:
        if any(yr in company_name for yr in ["2020", "2021", "2022", "2023", "2024"]):
            age["age_180_above"] += unallocated
        else:
            base_old = min(unallocated, abs(opening_bal_num or 0.0))
            rem = max(0.0, unallocated - base_old)
            age["age_180_above"] += base_old
            age["age_0_30"] += round(rem * 0.45, 2)
            age["age_30_60"] += round(rem * 0.25, 2)
            age["age_60_90"] += round(rem * 0.15, 2)
            age["age_90_120"] += round(rem * 0.10, 2)
            age["age_120_150"] += round(rem * 0.05, 2)

    for k in age:
        age[k] = round(age[k], 2)

    return age


def fetch_open_companies_from_tally(tally_url: str, timeout: int = 10) -> list[str]:
    url = normalize_url(tally_url)
    xml_req = build_company_list_xml()
    res = requests.post(
        url,
        data=xml_req.encode("utf-8"),
        headers={"Content-Type": "text/xml;charset=utf-8"},
        timeout=timeout
    )
    res.raise_for_status()

    root = ET.fromstring(res.text)
    companies = []
    for comp_elem in root.iter("COMPANY"):
        name = comp_elem.get("NAME") or parse_safe_text(comp_elem.find("NAME"))
        if name and name not in companies:
            companies.append(name)
    return companies


def fetch_ledgers_from_tally(tally_url: str, company_name: str = "", group_name: str = "Sundry Debtors", timeout: int = 25) -> list[dict]:
    url = normalize_url(tally_url)
    xml_req = build_ledger_list_xml(group_name=group_name, company_name=company_name)
    res = requests.post(
        url,
        data=xml_req.encode("utf-8"),
        headers={"Content-Type": "text/xml;charset=utf-8"},
        timeout=timeout
    )
    res.raise_for_status()

    root = ET.fromstring(res.text)
    ledgers = []

    for l_elem in root.iter("LEDGER"):
        name = l_elem.get("NAME") or parse_safe_text(l_elem.find("NAME"))
        if not name:
            continue

        parent = parse_safe_text(l_elem.find("PARENT")) or group_name
        gstin = parse_safe_text(l_elem.find("PARTYGSTIN")) or parse_safe_text(l_elem.find("GSTIN"))
        gstin = gstin.upper().strip()
        pan = parse_safe_text(l_elem.find("INCOMETAXNUMBER")) or parse_safe_text(l_elem.find("PAN"))
        pan = pan.upper().strip()
        if not pan and gstin and len(gstin) >= 12:
            pan = gstin[2:12]

        addr_lines = [parse_safe_text(a) for a in l_elem.findall(".//ADDRESS") if parse_safe_text(a)]
        address = ", ".join(addr_lines)

        state = parse_safe_text(l_elem.find("STATENAME")) or parse_safe_text(l_elem.find("STATE"))
        if not state and gstin and len(gstin) >= 2:
            code = gstin[:2]
            state = GST_STATE_MAP.get(code, "")

        mobile = parse_safe_text(l_elem.find("LEDGERMOBILE")) or parse_safe_text(l_elem.find("MOBILE"))
        phone = parse_safe_text(l_elem.find("LEDGERPHONE")) or parse_safe_text(l_elem.find("PHONE"))
        if not mobile and not phone and address:
            m_match = re.search(r"(?:MO\.?\s*NO\.?[:\s]*|MOB(?:ILE)?\.?[:\s]*)([0-9,\s/]+)", address, re.IGNORECASE)
            if m_match:
                mobile = m_match.group(1).strip()
            else:
                num_match = re.search(r"\b([6789]\d{9})\b", address)
                if num_match:
                    mobile = num_match.group(1)

        email = parse_safe_text(l_elem.find("EMAIL")) or parse_safe_text(l_elem.find("EMAILID"))

        closing_balance_raw = parse_safe_text(l_elem.find("CLOSINGBALANCE"))
        opening_balance_raw = parse_safe_text(l_elem.find("OPENINGBALANCE"))
        c_bal, c_type = parse_amount(None, closing_balance_raw)
        o_bal, o_type = parse_amount(None, opening_balance_raw)

        ageing = calculate_ageing_from_ledger_elem(l_elem, c_bal if c_type == "Dr" else -c_bal, o_bal if o_type == "Dr" else -o_bal, company_name)

        ledgers.append({
            "name": name,
            "customer_name": name,
            "company": company_name,
            "parent": parent,
            "gstin": gstin,
            "pan": pan,
            "phone": phone or mobile,
            "mobile": mobile,
            "email": email,
            "address": address,
            "state": state,
            "closing_balance": c_bal,
            "opening_balance": o_bal,
            "balance_type": c_type,
            "closingBalanceRaw": closing_balance_raw,
            "openingBalanceRaw": opening_balance_raw,
            **ageing
        })

    return ledgers


def sync_customer_records(raw_customers: list, default_company: str = None) -> dict:
    """
    Synchronizes customer list into tabCustomer and child tabCustomer Company Outstanding.
    Matches priority:
      1. GSTIN (exact match, normalized without spaces or hyphens)
      2. PAN (exact match)
      3. Customer Name (case-insensitive trimmed)
    """
    if not raw_customers:
        return {
            "success": False,
            "message": "No customer records provided for synchronization.",
            "created_count": 0,
            "updated_count": 0,
            "total_synced": 0,
            "companies": []
        }

    grouped = {}
    all_companies = set()

    for item in raw_customers:
        name = (item.get("name") or item.get("customer_name") or item.get("mailingName") or "").strip()
        if not name:
            continue

        gstin = (item.get("gstin") or item.get("gst_number") or "").strip().upper()
        pan = (item.get("pan") or "").strip().upper()
        if not pan and gstin and len(gstin) >= 12:
            pan = gstin[2:12]

        if gstin and len(gstin) >= 10:
            group_key = f"GST:{gstin}"
        elif pan and len(pan) == 10:
            group_key = f"PAN:{pan}"
        else:
            group_key = f"NAME:{name.lower()}"

        if group_key not in grouped:
            grouped[group_key] = {
                "name": name,
                "gstin": gstin,
                "pan": pan,
                "phone": (item.get("phone") or "").replace("—", "").strip(),
                "mobile": (item.get("mobile") or "").replace("—", "").strip(),
                "email": (item.get("email") or "").replace("—", "").strip(),
                "address": (item.get("address") or "").replace("—", "").strip(),
                "city": (item.get("city") or "").replace("—", "").strip(),
                "state": (item.get("state") or "").replace("—", "").strip(),
                "companies": {}
            }

        entry = grouped[group_key]
        if not entry["gstin"] and gstin:
            entry["gstin"] = gstin
        if not entry["pan"] and pan:
            entry["pan"] = pan
        if not entry["phone"] and item.get("phone"):
            entry["phone"] = item.get("phone").replace("—", "").strip()
        if not entry["mobile"] and item.get("mobile"):
            entry["mobile"] = item.get("mobile").replace("—", "").strip()
        if not entry["address"] and item.get("address"):
            entry["address"] = item.get("address").replace("—", "").strip()
        if not entry["city"] and item.get("city"):
            entry["city"] = item.get("city").replace("—", "").strip()
        if not entry["state"] and item.get("state"):
            entry["state"] = item.get("state").replace("—", "").strip()

        comp_name = (item.get("company") or item.get("company_name") or default_company or "Main Company").strip()
        all_companies.add(comp_name)

        if item.get("company_outstandings") and isinstance(item["company_outstandings"], list):
            for co in item["company_outstandings"]:
                c_comp = (co.get("company") or co.get("company_name") or comp_name).strip()
                all_companies.add(c_comp)
                c_bal, c_type = parse_amount(co.get("closing_balance"), co.get("closingBalanceRaw"))
                c_open, _ = parse_amount(co.get("opening_balance"), co.get("openingBalanceRaw"))
                entry["companies"][c_comp] = {
                    "closing_balance": c_bal,
                    "opening_balance": c_open,
                    "balance_type": co.get("balance_type") or c_type,
                    "age_0_30": flt(co.get("age_0_30", 0.0)),
                    "age_30_60": flt(co.get("age_30_60", 0.0)),
                    "age_60_90": flt(co.get("age_60_90", 0.0)),
                    "age_90_120": flt(co.get("age_90_120", 0.0)),
                    "age_120_150": flt(co.get("age_120_150", 0.0)),
                    "age_150_180": flt(co.get("age_150_180", 0.0)),
                    "age_180_above": flt(co.get("age_180_above", 0.0)),
                }
        else:
            c_bal, c_type = parse_amount(item.get("closing_balance") or item.get("closingBalance"), item.get("closingBalanceRaw"))
            c_open, _ = parse_amount(item.get("opening_balance") or item.get("openingBalance"), item.get("openingBalanceRaw"))
            entry["companies"][comp_name] = {
                "closing_balance": c_bal,
                "opening_balance": c_open,
                "balance_type": item.get("balance_type") or c_type,
                "age_0_30": flt(item.get("age_0_30", 0.0)),
                "age_30_60": flt(item.get("age_30_60", 0.0)),
                "age_60_90": flt(item.get("age_60_90", 0.0)),
                "age_90_120": flt(item.get("age_90_120", 0.0)),
                "age_120_150": flt(item.get("age_120_150", 0.0)),
                "age_150_180": flt(item.get("age_150_180", 0.0)),
                "age_180_above": flt(item.get("age_180_above", 0.0)),
            }

    # Auto-ensure Company doc exists
    for comp in all_companies:
        if comp and not frappe.db.exists("Company", comp):
            try:
                frappe.get_doc({
                    "doctype": "Company",
                    "company_name": comp,
                    "tally_company_name": comp,
                    "active": 1
                }).insert(ignore_permissions=True)
            except Exception:
                pass

    created_count = 0
    updated_count = 0
    results = []
    now_time = now_datetime()

    for group_key, data in grouped.items():
        gst = data["gstin"]
        pan = data["pan"]
        cust_name = data["name"]

        matched_doc_name = None

        if gst and len(gst) >= 10:
            res = frappe.db.sql(
                """SELECT name FROM `tabCustomer`
                   WHERE REPLACE(REPLACE(UPPER(gstin), ' ', ''), '-', '') = %s
                   LIMIT 1""",
                (gst.replace(" ", "").replace("-", ""),),
                as_dict=True
            )
            if res:
                matched_doc_name = res[0]["name"]

        if not matched_doc_name and pan and len(pan) == 10:
            res = frappe.db.sql(
                """SELECT name FROM `tabCustomer`
                   WHERE UPPER(pan) = %s
                      OR UPPER(gstin) LIKE %s
                   LIMIT 1""",
                (pan, f"%{pan}%"),
                as_dict=True
            )
            if res:
                matched_doc_name = res[0]["name"]

        if not matched_doc_name and cust_name:
            res = frappe.db.sql(
                """SELECT name FROM `tabCustomer`
                   WHERE LOWER(TRIM(customer_name)) = %s
                      OR LOWER(TRIM(name)) = %s
                   LIMIT 1""",
                (cust_name.lower().strip(), cust_name.lower().strip()),
                as_dict=True
            )
            if res:
                matched_doc_name = res[0]["name"]

        is_new = False
        if matched_doc_name:
            cust_doc = frappe.get_doc("Customer", matched_doc_name)
            if not cust_doc.gstin and gst:
                cust_doc.gstin = gst
            if not cust_doc.pan and pan:
                cust_doc.pan = pan
            if not cust_doc.phone and (data["phone"] or data["mobile"]):
                cust_doc.phone = data["phone"] or data["mobile"]
            if not cust_doc.mobile and data["mobile"]:
                cust_doc.mobile = data["mobile"]
            if not cust_doc.email and data["email"]:
                cust_doc.email = data["email"]
            if not cust_doc.city and data["city"]:
                cust_doc.city = data["city"]
            if not cust_doc.state and data["state"]:
                cust_doc.state = data["state"]
            if not cust_doc.address and data["address"]:
                cust_doc.address = data["address"]
        else:
            is_new = True
            cust_doc = frappe.new_doc("Customer")
            cust_doc.customer_name = cust_name
            cust_doc.gstin = gst or ""
            cust_doc.pan = pan or ""
            cust_doc.phone = data["phone"] or data["mobile"] or ""
            cust_doc.mobile = data["mobile"] or ""
            cust_doc.email = data["email"] or ""
            cust_doc.city = data["city"] or ""
            cust_doc.state = data["state"] or ""
            cust_doc.address = data["address"] or ""
            cust_doc.active = 1

        cust_doc.last_sync = now_time

        # Update company outstandings child rows
        existing_rows = {row.company_name: row for row in (cust_doc.company_outstandings or [])}

        for comp, bal_info in data["companies"].items():
            if comp in existing_rows:
                row = existing_rows[comp]
                row.closing_balance = bal_info["closing_balance"]
                row.opening_balance = bal_info["opening_balance"]
                row.balance_type = bal_info["balance_type"]
                row.tally_company = comp
                row.last_sync = now_time
                row.age_0_30 = bal_info["age_0_30"]
                row.age_30_60 = bal_info["age_30_60"]
                row.age_60_90 = bal_info["age_60_90"]
                row.age_90_120 = bal_info["age_90_120"]
                row.age_120_150 = bal_info["age_120_150"]
                row.age_150_180 = bal_info["age_150_180"]
                row.age_180_above = bal_info["age_180_above"]
            else:
                cust_doc.append("company_outstandings", {
                    "company_name": comp,
                    "tally_company": comp,
                    "closing_balance": bal_info["closing_balance"],
                    "opening_balance": bal_info["opening_balance"],
                    "balance_type": bal_info["balance_type"],
                    "last_sync": now_time,
                    "age_0_30": bal_info["age_0_30"],
                    "age_30_60": bal_info["age_30_60"],
                    "age_60_90": bal_info["age_60_90"],
                    "age_90_120": bal_info["age_90_120"],
                    "age_120_150": bal_info["age_120_150"],
                    "age_150_180": bal_info["age_150_180"],
                    "age_180_above": bal_info["age_180_above"],
                })

        # Calculate total net outstanding & sum ageing buckets across all companies
        total_out = 0.0
        sum_0_30 = 0.0
        sum_30_60 = 0.0
        sum_60_90 = 0.0
        sum_90_120 = 0.0
        sum_120_150 = 0.0
        sum_150_180 = 0.0
        sum_180_above = 0.0

        for row in (cust_doc.company_outstandings or []):
            c_bal = float(row.closing_balance or 0.0)
            if row.balance_type == "Cr":
                total_out -= c_bal
            else:
                total_out += c_bal

            sum_0_30 += float(row.age_0_30 or 0.0)
            sum_30_60 += float(row.age_30_60 or 0.0)
            sum_60_90 += float(row.age_60_90 or 0.0)
            sum_90_120 += float(row.age_90_120 or 0.0)
            sum_120_150 += float(row.age_120_150 or 0.0)
            sum_150_180 += float(row.age_150_180 or 0.0)
            sum_180_above += float(row.age_180_above or 0.0)

        cust_doc.total_outstanding = round(total_out, 2)
        cust_doc.balance_type = "Cr" if total_out < 0 else ("Dr" if total_out > 0 else "Zero")
        cust_doc.age_0_30 = round(sum_0_30, 2)
        cust_doc.age_30_60 = round(sum_30_60, 2)
        cust_doc.age_60_90 = round(sum_60_90, 2)
        cust_doc.age_90_120 = round(sum_90_120, 2)
        cust_doc.age_120_150 = round(sum_120_150, 2)
        cust_doc.age_150_180 = round(sum_150_180, 2)
        cust_doc.age_180_above = round(sum_180_above, 2)

        cust_doc.save(ignore_permissions=True)

        if is_new:
            created_count += 1
        else:
            updated_count += 1

        results.append({
            "id": cust_doc.name,
            "customer_name": cust_doc.customer_name,
            "is_new": is_new,
            "total_outstanding": cust_doc.total_outstanding,
            "balance_type": cust_doc.balance_type,
            "companies_synced": list(data["companies"].keys())
        })

    frappe.db.commit()

    return {
        "success": True,
        "message": f"Successfully synced {len(results)} customers ({created_count} created, {updated_count} updated) across {len(all_companies)} companies.",
        "created_count": created_count,
        "updated_count": updated_count,
        "total_synced": len(results),
        "companies": sorted(list(all_companies)),
        "customers": results[:10]
    }
