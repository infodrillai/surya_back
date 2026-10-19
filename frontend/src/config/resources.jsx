/**
 * One config per screen. CrudPage + DocForm turn these into list, form, validation and live maths.
 * @typedef {{name:string,label:string,type?:string,master?:string,doctype?:string,filter?:Function,required?:boolean,
 *   readOnly?:boolean,readOnlyOnEdit?:boolean,summary?:boolean,positive?:boolean,showIf?:Function,options?:string[]}} FieldConfig
 */
import { LinearProgress, Stack, Typography, Chip } from '@mui/material';
import { call, deleteDoc, getDoc, insertDoc, runAction, updateDoc } from '../api/client';
import { db } from '../db/dexie';
import { purchaseCalc, salesCalc, stageCalc } from '../lib/formulas';
import { todayISO } from '../lib/format';

// ---- field helpers ---------------------------------------------------------
const t = (name, label, x = {}) => ({ name, label, type: 'text', ...x });
const num = (name, label, x = {}) => ({ name, label, type: 'number', ...x });
const cur = (name, label, x = {}) => ({ name, label, type: 'currency', ...x });
const date = (name, label, x = {}) => ({ name, label, type: 'date', default: todayISO, ...x });
const link = (name, label, master, x = {}) => ({ name, label, type: 'link', master, ...x });
const sel = (name, label, options, x = {}) => ({ name, label, type: 'select', options, ...x });
const ro = (f) => ({ ...f, readOnly: true });
const sum = (f) => ({ ...f, readOnly: true, summary: true, default: () => 0 });
const status = { field: 'is_completed', label: 'Status', type: 'doc-status' };
const col = (field, label, type) => ({ field, label, type });


// ---- simple masters --------------------------------------------------------
const simple = (doctype, nameField, title, x = {}) => ({
  doctype, master: true, title, plural: x.plural,
  fields: [t(nameField, `${title} name`, { required: true, readOnlyOnEdit: true })],
  columns: [col(nameField, `${title} name`)],
});
const contact = [t('gstin', 'GSTIN'), t('state', 'State'), t('phone', 'Phone'), { name: 'address', label: 'Address', type: 'textarea' }];
const contactCols = [col('name', 'Name'), col('gstin', 'GSTIN'), col('state', 'State'), col('phone', 'Phone')];
const customerCols = [col('name', 'Name'), col('gstin', 'GSTIN'), col('city', 'City'), col('phone', 'Phone'), col('total_outstanding', 'Outstanding', 'currency')];

const uom = { ...simple('UOM', 'uom_name', 'UOM'), plural: 'Units of measure' };
const process = { ...simple('Process', 'process_name', 'Process'), plural: 'Processes' };
const category = { ...simple('Category', 'category_name', 'Category'), plural: 'Categories' };
const charge = { ...simple('Charge', 'charge_name', 'Charge'), subtitle: 'Labour, electricity and other Stage 3 charges.' };
const vendor = { doctype: 'Vendor', master: true, title: 'Vendor', fields: [t('vendor_name', 'Vendor name', { required: true, readOnlyOnEdit: true }), ...contact], columns: contactCols, subtitle: 'State decides CGST + SGST or IGST on purchases.' };
const customer = {
  doctype: 'Customer',
  master: true,
  title: 'Customer',
  fields: [
    t('customer_name', 'Customer name', { required: true, readOnlyOnEdit: true }),
    t('gstin', 'GSTIN'),
    t('pan', 'PAN'),
    t('phone', 'Phone'),
    t('mobile', 'Mobile'),
    t('email', 'Email'),
    t('city', 'City'),
    t('state', 'State'),
    { name: 'address', label: 'Address', type: 'textarea' },
    ro(cur('total_outstanding', 'Total Outstanding')),
  ],
  columns: customerCols,
};


// ---- Product (with its BOM inside) -----------------------------------------
// The BOM is no longer a separate screen: it is saved as the product's own BOM document.
const raw = (r) => r.product_type === 'Raw';
const bomRow = (extra = []) => [link('process', 'Process', 'Process'), link('product', 'Raw material', 'Product', { filter: raw, required: true, minWidth: 220 }), num('per_unit_utilization', 'Per-unit utilization', { positive: true }), ...extra];
const BOM_TABLES = ['stage1_items', 'stage2_items', 'stage3_charges'];
const steps = (v) => (v?.product_type && v.product_type !== 'Raw' ? Number(v.total_steps) || 3 : 0);

const product = {
  doctype: 'Product', master: true, title: 'Product', tableTabs: true,
  tableTabsEmpty: 'Raw products do not use a BOM. Select Product type "Semi" or "Finished" to configure BOM stages 1, 2, and 3.',
  subtitle: 'Raw, semi-finished and finished products. Semi / Finished products carry their BOM stages here.',
  fields: [
    t('product_name', 'Product name', { required: true }),
    t('product_code', 'Product code', { required: true, readOnlyOnEdit: true }),
    sel('product_type', 'Product type', ['Raw', 'Semi', 'Finished'], { required: true, default: () => 'Raw' }),
    link('uom', 'UOM', 'UOM', { required: true }),
    link('category', 'Category', 'Category'),
    sel('total_steps', 'BOM Stages (Total steps)', [
      { value: 1, label: '1 Stage (Stage 1 only)' },
      { value: 2, label: '2 Stages (Stage 1 & 2)' },
      { value: 3, label: '3 Stages (Stage 1, 2 & 3)' },
    ], {
      showIf: (v) => v.product_type && v.product_type !== 'Raw',
      default: () => 3,
    }),
    num('low_stock_limit', 'Low stock limit'),
    num('high_stock_limit', 'High stock limit'),
    { name: 'is_scrap', label: 'Scrap / wastage product', type: 'check' },
    { name: 'allow_negative_stock', label: 'Allow negative stock', type: 'check' },
  ],
  tables: [
    {
      name: 'stage1_items',
      label: 'BOM · Stage 1 (Raw materials & Scrap)',
      empty: 'Add Stage 1 raw materials and optional scrap/wastage product.',
      fields: bomRow([link('wastage_product', 'Wastage scrap product', 'Product', { filter: (r) => !!r.is_scrap, minWidth: 200 })]),
      showIf: (v) => steps(v) >= 1,
      newRow: () => ({ per_unit_utilization: '' }),
    },
    {
      name: 'stage2_items',
      label: 'BOM · Stage 2 (Secondary raw materials)',
      empty: 'Add Stage 2 raw materials.',
      fields: bomRow(),
      showIf: (v) => steps(v) >= 2,
      newRow: () => ({ per_unit_utilization: '' }),
    },
    {
      name: 'stage3_charges',
      label: 'BOM · Stage 3 (Charges & Overhead)',
      empty: 'Add Stage 3 charges (e.g. Labour, Electricity, Finishing).',
      fields: [
        link('charge', 'Charge', 'Charge', { required: true, minWidth: 200 }),
        cur('per_unit_price', 'Price per unit', { positive: true }),
        { name: 'in_tooling_base', label: 'In tooling base', type: 'check' },
      ],
      showIf: (v) => steps(v) >= 3,
      newRow: () => ({ per_unit_price: '', in_tooling_base: 0 }),
    },
  ],
  validate: (v) => {
    const e = {};
    if (v.product_type && v.product_type !== 'Raw') {
      const numSteps = Number(v.total_steps) || 3;
      if (![1, 2, 3].includes(numSteps)) e.total_steps = 'Select 1, 2 or 3 stages';
      if (numSteps >= 1 && !v.stage1_items?.length) e.stage1_items = 'Add Stage 1 BOM rows';
      if (numSteps >= 2 && !v.stage2_items?.length) e.stage2_items = 'Add Stage 2 BOM rows';
      if (numSteps >= 3 && !v.stage3_charges?.length) e.stage3_charges = 'Add Stage 3 charges';
    }
    return e;
  },
  // saved as a second document (BOM, named after the product) right after the Product
  companion: {
    doctype: 'BOM',
    tables: BOM_TABLES,
    async load(row) {
      let b = await db.BOM.get(row.name);
      if (!b) {
        try {
          b = await getDoc('BOM', row.name);
        } catch (_) {
          b = null;
        }
      }
      return b ? Object.fromEntries(BOM_TABLES.map((k) => [k, b[k] || []])) : {};
    },
    async save(saved, tables) {
      let exists = !!(await db.BOM.get(saved.name));
      if (!exists) {
        try {
          exists = !!(await getDoc('BOM', saved.name));
        } catch (_) {
          exists = false;
        }
      }
      if (saved.product_type === 'Raw') { if (exists) await deleteDoc('BOM', saved.name); return; }
      const s = Number(saved.total_steps) || 3;
      const body = {
        product: saved.name,
        stage1_items: tables.stage1_items || [],
        stage2_items: s >= 2 ? tables.stage2_items || [] : [],
        stage3_charges: s >= 3 ? tables.stage3_charges || [] : [],
      };
      if (exists) await updateDoc('BOM', saved.name, body);
      else await insertDoc('BOM', body);
    },
  },
  columns: [
    col('product_code', 'Code'),
    col('product_name', 'Name'),
    col('product_type', 'Type'),
    col('uom', 'UOM'),
    col('category', 'Category'),
    col('total_steps', 'Steps', 'number'),
  ],
};

// ---- Purchase --------------------------------------------------------------
const purchase = {
  doctype: 'Purchase Entry', title: 'Purchase', plural: 'Purchases', completable: true, subtitle: 'Vendor bills. Completing a purchase adds Raw stock at landed cost.',
  fields: [
    link('vendor', 'Vendor', 'Vendor', { required: true }), date('posting_date', 'Date', { required: true }), t('bill_no', 'Bill no', { required: true }), ro(t('vendor_state', 'Vendor state')),
    cur('extra_charges', 'Extra charges', { required: false, default: () => 0 }),
    sum(cur('taxable_amount', 'Taxable amount')), sum(cur('tax_amount', 'Tax amount', { required: false, default: () => 0 })), sum(cur('grand_total', 'Grand total')),
  ],
  tables: [{
    name: 'items', label: 'Items', newRow: () => ({ quantity: '', rate: '', gst_percent: 0, extra_charge: 0, cgst: 0, sgst: 0, igst: 0, amount: 0, landed_rate: 0 }), empty: 'Add the raw materials on this bill.',
    fields: [link('product', 'Product', 'Product', { filter: raw, required: true, minWidth: 220, labelField: 'product_name' }), num('quantity', 'Qty', { positive: true }), ro(t('uom', 'UOM')), cur('rate', 'Rate'), num('gst_percent', 'GST %', { max: 100 }), cur('extra_charge', 'Extra charge'), ro(cur('amount', 'Amount')), ro(cur('cgst', 'CGST')), ro(cur('sgst', 'SGST')), ro(cur('igst', 'IGST')), ro(cur('landed_rate', 'Landed rate', { dp: 4 }))],
  }],
  compute: (v, ctx) => purchaseCalc(v, ctx),
  validate: (v) => (v.items?.length ? {} : { items: 'Add at least one item' }),
  columns: [col('name', 'No'), col('vendor', 'Vendor'), col('posting_date', 'Date', 'date'), col('bill_no', 'Bill no'), col('extra_charges', 'Extra charges'), col('grand_total', 'Grand total', 'currency'), status],
};

// ---- Stage batches ---------------------------------------------------------
const stageRows = (stage) => async (v) => {
  const r = await call('clssurya.api.get_stage_rows', { product: v.product, qty: v.quantity, stage });
  return { top: { wastage_product: r.wastage_product || '' }, tables: { items: r.items, ...(stage === 3 ? { charges: r.charges } : {}) } };
};
const itemFields = [
  link('process', 'Process', 'Process', { readOnly: true }), link('product', 'Product', 'Product', { readOnly: true, minWidth: 200 }),
  ro(num('per_unit_utilization', 'Per unit', { dp: 4 })), ro(num('total_utilization', 'Estimate', { dp: 4 })),
  num('actual_utilization', 'Actual used'), ro(cur('unit_price', 'Unit price', { dp: 4 })), ro(cur('actual_amount', 'Actual amount')),
  cur('extra_cost', 'Extra cost / pc'),
];
const stageConfig = (stage) => ({
  doctype: `Stage ${stage} Batch`, title: `Stage ${stage} batch`, plural: `Stage ${stage} batches`, completable: true, summaryTitle: 'Live cost',
  fields: [
    link('product', stage === 3 ? 'Finished product' : 'Product to produce', 'Product', { required: true, minWidth: 240, filter: (r) => r.product_type !== 'Raw' && Number(r.total_steps) >= stage }),
    num('quantity', 'Quantity produced', { positive: true }), date('posting_date', 'Date'),
    ...(stage === 1 ? [num('weight_per_piece', 'Weight per piece', { positive: true }), ro(num('wastage_qty', 'Wastage (to scrap)', { dp: 4 }))] : []),
    // Stage 3: tooling % is typed by hand and works on carried cost + the charges ticked "In tooling base"
    ...(stage === 3 ? [num('tooling_percent', 'Tooling cost %', { max: 100 }), ro(cur('tooling_base', 'Tooling base (carried + ticked charges)', { minWidth: 220 }))] : []),
    num('rejection_percent', stage === 3 ? 'Rejection % (on everything)' : 'Rejection %', { max: 99.99 }),
    sum(cur('carried_cost', 'Carried cost')), sum(cur('added_cost', 'Added cost')),
    ...(stage === 3 ? [sum(cur('tooling_amount', 'Tooling cost'))] : []),
    sum(cur('rejection_amount', 'Rejection')), sum(cur('batch_total', 'Batch total')), sum(cur('unit_cost', 'Unit cost', { dp: 4 })),
  ],
  tables: [
    { name: 'items', label: stage === 1 ? 'Raw materials' : stage === 2 ? 'Consumption (carried-in + raw)' : 'Carried-in Stage 2 stock', fields: itemFields, noAdd: true },
    ...(stage === 3 ? [{ name: 'charges', label: 'Charges', noAdd: true, fields: [link('charge', 'Charge', 'Charge', { readOnly: true }), cur('per_unit_price', 'Per unit'), { name: 'in_tooling_base', label: 'In tooling base', type: 'check' }, ro(cur('amount', 'Amount'))] }] : []),
  ],

  // one calculation, shared with the tests (extra cost, tooling and rejection are all inside stageCalc)
  compute: (v) => stageCalc(stage, v),

  loadKey: (v) => (v.product && Number(v.quantity) > 0 ? `${v.product}|${v.quantity}` : null),
  loadRows: stageRows(stage),
  columns: [col('name', 'No'), col('product', 'Product'), col('quantity', 'Quantity', 'number'), col('unit_cost', 'Unit cost', 'currency'), col('batch_total', 'Batch total', 'currency'), status],
});
export const STAGE_CONFIGS = [stageConfig(1), stageConfig(2), stageConfig(3)];

// ---- Sales -----------------------------------------------------------------
const finished = (r) => r.product_type === 'Finished';
const belowBanner = (v) => (v.below_cost ? { severity: 'warning', text: 'One or more rows are priced below production cost.' } : null);
const salesRow = [link('product', 'Product', 'Product', { required: true, minWidth: 220, labelField: 'product_name' }), num('quantity', 'Qty', { positive: true }), ro(t('uom', 'UOM')), ro(cur('production_cost', 'Cost / unit', { dp: 4 })), cur('rate', 'Rate'), ro(cur('amount', 'Amount'))];


const quotation = {
  doctype: 'Quotation',
  title: 'Quotation',
  usesFinishedCost: true,
  subtitle: 'Quotation with discount, GST and versioning.',

  isLocked: (d) =>
    ['Superseded', 'Accepted'].includes(d?.status),

  fields: [
    link('customer', 'Customer', 'Customer', { required: true }),
    date('quotation_date', 'Date'),

    {
      name: 'status',
      label: 'Status',
      type: 'select',
      options: ['Draft', 'Sent', 'Accepted', 'Rejected'],
      default: () => 'Draft',
    },

    ro(num('version', 'Version', { dp: 0 })),
    ro(t('parent_quotation', 'Previous version')),

    // Discount

    num('discount_percent', 'Discount (%)', {
      default: () => 0,
    }),

    sum(cur('subtotal', 'Subtotal')),
    cur('discount_amount', 'Discount Amount'),
    cur('taxable_amount', 'Taxable Amount'),

    num('gst_percent', 'GST (%)', {
      default: () => 18,
    }),

    cur('cgst_amount', 'CGST'),
    cur('sgst_amount', 'SGST'),
    cur('igst_amount', 'IGST'),

    sum(cur('total_amount', 'Total Amount')),
    sum(cur('grand_total', 'Grand Total')),

  ],

  tables: [{
    name: 'items',
    label: 'Items',
    fields: salesRow,
    newRow: () => ({ quantity: '', rate: '' }),
    empty: 'Add finished products to quote.',
  }],

  compute: (v, ctx) => salesCalc(v, ctx),
  banner: belowBanner,

  validate: (v) => {
    const errors = {};

    if (!v.items?.length) {
      errors.items = 'Add at least one item';
    }

    if (Number(v.discount_percent) < 0 ||
      Number(v.discount_percent) > 100) {
      errors.discount_percent =
        'Discount must be between 0 and 100';
    }

    if (Number(v.gst_percent) < 0 ||
      Number(v.gst_percent) > 100) {
      errors.gst_percent =
        'GST must be between 0 and 100';
    }

    return errors;
  },

  columns: [
    col('name', 'No'),
    col('customer', 'Customer'),
    col('version', 'Version', 'number'),
    col('quotation_date', 'Date', 'date'),
    col('total_amount', 'Grand total', 'currency'),
    col('status', 'Status', 'status'),
    col('below_cost', '', 'flag'),
  ],

  rowActions: [
    {
      key: 'revise',
      label: 'Revise',
      show: (r) => r.status !== 'Superseded',
      run: async (r) =>
        `Created ${(await runAction('Quotation', r.name, 'revise')).result
        }`,
    },
    {
      key: 'order',
      label: 'Create order',
      show: (r) => ['Draft', 'Sent'].includes(r.status),
      run: async (r) =>
        `Created ${(await runAction(
          'Quotation',
          r.name,
          'make_sales_order'
        )).result
        }`,
    },
  ],
};


const salesOrder = {
  doctype: 'Sales Order', title: 'Sales order', plural: 'Sales orders', usesFinishedCost: true, subtitle: 'Admin approves. Stock is deducted only when goods are dispatched.',
  isLocked: (d) => !!d?.status && d.status !== 'Pending Approval',
  fields: [link('customer', 'Customer', 'Customer', { required: true }), date('order_date', 'Order date'), ro(t('status', 'Status')), sum(cur('total_amount', 'Total'))],
  tables: [{ name: 'items', label: 'Items', fields: [...salesRow.slice(0, 5), ro(cur('amount', 'Amount')), ro(num('dispatched_qty', 'Dispatched')), ro(num('pending_qty', 'Pending'))], newRow: () => ({ quantity: '', rate: '' }) }],
  compute: (v, ctx) => salesCalc(v, ctx), banner: belowBanner,
  header: (v) => {
    const ordered = (v.items || []).reduce((s, r) => s + (Number(r.quantity) || 0), 0);
    const sent = (v.items || []).reduce((s, r) => s + (Number(r.dispatched_qty) || 0), 0);
    return ordered && sent ? (
      <Stack spacing={0.5}><Typography variant="body2">Dispatched {sent} of {ordered}</Typography><LinearProgress variant="determinate" value={Math.min(100, (sent / ordered) * 100)} sx={{ height: 8, borderRadius: 4 }} /></Stack>
    ) : null;
  },
  validate: (v) => (v.items?.length ? {} : { items: 'Add at least one item' }),
  columns: [col('name', 'No'), col('customer', 'Customer'), col('order_date', 'Date', 'date'), col('total_amount', 'Total', 'currency'), col('status', 'Status', 'status'), col('below_cost', '', 'flag')],
  rowActions: [{ key: 'approve', label: 'Approve', show: (r, admin) => admin && r.status === 'Pending Approval', run: async (r) => { await runAction('Sales Order', r.name, 'approve'); return `${r.name} approved`; } }],
};

const dispatch = {
  doctype: 'Dispatch', title: 'Dispatch', plural: 'Dispatches', completable: true, usesFinishedCost: true, subtitle: 'Ship against an approved order. Completing deducts Finished stock.',
  fields: [
    { name: 'sales_order', label: 'Sales order', type: 'link', doctype: 'Sales Order', required: true, readOnlyOnEdit: true, filter: (r) => ['Approved', 'Partially Dispatched'].includes(r.status), minWidth: 240 },
    ro(t('customer', 'Customer')), date('dispatch_date', 'Dispatch date'), { name: 'remarks', label: 'Vehicle / challan', type: 'textarea' },
  ],
  tables: [{ name: 'items', label: 'Order lines', noAdd: true, fields: [ro(t('product', 'Product')), ro(num('ordered_qty', 'Ordered')), ro(num('already_dispatched', 'Already sent')), num('quantity', 'Dispatch now'), ro(cur('unit_cost', 'Cost / unit', { dp: 4 }))] }],
  loadKey: (v) => v.sales_order || null,
  loadRows: async (v, { finishedCost }) => {
    const so = await getDoc('Sales Order', v.sales_order);
    return {
      top: { customer: so.customer },
      tables: { items: so.items.filter((i) => i.quantity - i.dispatched_qty > 0).map((i) => ({ order_item: i.name, product: i.product, ordered_qty: i.quantity, already_dispatched: i.dispatched_qty, quantity: i.quantity - i.dispatched_qty, unit_cost: finishedCost?.[i.product]?.unit_price || 0 })) },
    };
  },
  validate: (v) => {
    const e = {};
    (v.items || []).forEach((r, i) => { if (Number(r.quantity) > Number(r.ordered_qty) - Number(r.already_dispatched) + 1e-9) e[`items.${i}.quantity`] = 'More than remaining'; });
    return e;
  },
  columns: [col('name', 'No'), col('sales_order', 'Sales order'), col('customer', 'Customer'), col('dispatch_date', 'Date', 'date'), status],
};

const inventory = {
  doctype: 'Inventory', title: 'Stock', plural: 'Inventory by stage', readOnlyList: true, subtitle: 'Quantity and weighted-average price per product and stage.',
  fields: [], columns: [col('product', 'Product'), col('stage', 'Stage'), col('stock', 'Stock', 'number'), col('unit_price', 'Unit price', 'currency'), col('total_amount', 'Value', 'currency')],
};

/** Route path -> config. */
export const RESOURCES = {
  '/uom': uom, '/product': product, '/category': category, '/process': process, '/purchase': purchase,
  '/quotation': quotation, '/sales-order': salesOrder, '/vendor': vendor, '/customer': customer,
  '/charge': charge, '/dispatch': dispatch,
};