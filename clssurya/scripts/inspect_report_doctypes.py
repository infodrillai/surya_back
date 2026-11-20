import frappe

frappe.init(site='clssurya.local', sites_path='/home/rutva_javiya/frappe-bench/sites')
frappe.connect()

def inspect_doctype(dt):
    meta = frappe.get_meta(dt)
    print(f"=== {dt} Fields ===")
    for f in meta.fields:
        print(f"  {f.fieldname} ({f.fieldtype}) - {f.label}")

inspect_doctype('Sales Order')
inspect_doctype('Sales Order Item')
inspect_doctype('Dispatch')
inspect_doctype('Dispatch Item')
inspect_doctype('Purchase Entry')
inspect_doctype('Purchase Entry Item')

frappe.destroy()

