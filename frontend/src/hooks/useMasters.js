import { useLiveQuery } from 'dexie-react-hooks';
import { db, MASTERS } from '../db/dexie';

const EMPTY = Object.fromEntries(MASTERS.map((m) => [m, {}]));
const NONE = [];

/** Live list of one master from IndexedDB; dropdowns re-render as soon as the cache reloads. */
export const useMasters = (doctype) => useLiveQuery(() => db.table(doctype).toArray(), [doctype]) ?? NONE;

/** { Product: {code: record}, Vendor: {...}, ... } for synchronous lookups inside formulas. */
export const useMasterMaps = () =>
  useLiveQuery(async () => {
    const out = {};
    for (const m of MASTERS) out[m] = Object.fromEntries((await db.table(m).toArray()).map((r) => [r.name, r]));
    return out;
  }, []) ?? EMPTY;
