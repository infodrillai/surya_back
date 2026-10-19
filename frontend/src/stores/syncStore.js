import { create } from 'zustand';

/** @typedef {'idle'|'syncing'|'ready'|'error'} SyncStatus */
export const useSyncStore = create((set) => ({
  status: 'idle',
  versions: {},
  error: null,
  setStatus: (status, error = null) => set({ status, error }),
  setVersions: (versions) => set({ versions }),
}));
