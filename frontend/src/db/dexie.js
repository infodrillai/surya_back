import Dexie from 'dexie';

export const MASTERS = ['UOM', 'Process', 'Category', 'Charge', 'Vendor', 'Customer', 'Product', 'BOM', 'Company'];
export const SCHEMA_VERSION = 2; // bump to force every browser to wipe and reload

/** One table per master (keyed by name) plus a meta table (versions, user, schemaVersion). */
export const db = new Dexie('clssurya_erp');
db.version(1).stores({
  ...Object.fromEntries(['UOM', 'Process', 'Category', 'Charge', 'Vendor', 'Customer', 'Product', 'BOM'].map((m) => [m, 'name,modified'])),
  meta: 'key',
});
db.version(2).stores({
  Company: 'name,modified',
});
