import { call } from '../api/client';
import { DEPENDENT_QUERIES, queryClient } from '../api/queryClient';
import { useSyncStore } from '../stores/syncStore';
import { db, MASTERS, SCHEMA_VERSION } from './dexie';

const getMeta = async (key) => (await db.meta.get(key))?.value;
const setMeta = (key, value) => db.meta.put({ key, value });

/** Clear every master and the meta table (user switch, schema bump, logout). */
export async function wipeCache() {
  await db.transaction('rw', [...MASTERS.map((m) => db.table(m)), db.meta], async () => {
    await Promise.all(MASTERS.map((m) => db.table(m).clear()));
    await db.meta.clear();
  });
  useSyncStore.getState().setVersions({});
}

/** Wipe when a different user logs in or the schema version changed. */
export async function prepareCache(user) {
  if ((await getMeta('user')) !== user || (await getMeta('schemaVersion')) !== SCHEMA_VERSION) {
    await wipeCache();
    await setMeta('user', user);
    await setMeta('schemaVersion', SCHEMA_VERSION);
  }
}

const storedVersions = async () => Object.fromEntries(await Promise.all(MASTERS.map(async (m) => [m, await getMeta(`v:${m}`)])));

/** Reload the given masters in a single Dexie transaction and refresh dependent queries. */
export async function reloadMasters(list) {
  const { data, versions } = await call('clssurya.api.get_masters', { only: JSON.stringify(list) });
  const names = Object.keys(data).filter((m) => MASTERS.includes(m));
  await db.transaction('rw', [...names.map((m) => db.table(m)), db.meta], async () => {
    for (const m of names) {
      await db.table(m).clear();
      await db.table(m).bulkPut(data[m] || []);
      await setMeta(`v:${m}`, versions[m] ?? 0);
    }
  });
  const store = useSyncStore.getState();
  store.setVersions({ ...store.versions, ...versions });
  names.forEach((m) => (DEPENDENT_QUERIES[m] || []).forEach((key) => queryClient.invalidateQueries({ queryKey: key })));
}

/** Compare server counters with local ones; reload only what is missing or different. */
export async function syncMasters() {
  const store = useSyncStore.getState();
  try {
    store.setStatus('syncing');
    const server = await call('clssurya.api.get_master_versions', {}, { get: true });
    const local = await storedVersions();
    const stale = Object.keys(server).filter((m) => MASTERS.includes(m) && (local[m] === undefined || local[m] !== server[m]));
    if (stale.length) await reloadMasters(stale);
    else store.setVersions(local);
    store.setStatus('ready');
  } catch (e) {
    console.error('syncMasters failed:', e);
    store.setStatus('error', e.message);
  }
}
