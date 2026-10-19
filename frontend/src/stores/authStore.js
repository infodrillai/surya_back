import { create } from 'zustand';
import { call, login as apiLogin, logoutRequest, setCsrf, setUnauthorizedHandler } from '../api/client';
import { queryClient } from '../api/queryClient';
import { wipeCache } from '../db/masterCache';
import { stopRealtime } from '../db/realtime';

/** @typedef {{user:string, fullName:string, roles:string[], isAdmin:boolean, companyState:string}} Session */
export const useAuthStore = create((set, get) => ({
  status: 'loading', // loading | authed | anon
  user: null,
  fullName: '',
  roles: [],
  isAdmin: false,
  companyState: 'Gujarat',

  hasRole: (allowed) => get().isAdmin || !allowed || allowed.some((r) => get().roles.includes(r)),

  async bootstrap() {
    try {
      const me = await call('clssurya.api.me', {}, { get: true });
      setCsrf(await call('clssurya.api.get_csrf_token', {}, { get: true }));
      set({ status: 'authed', user: me.user, fullName: me.full_name, roles: me.roles, isAdmin: me.is_admin, companyState: me.company_state });
    } catch {
      set({ status: 'anon' });
    }
  },

  async login(usr, pwd) {
    await apiLogin(usr, pwd);
    await get().bootstrap();
  },

  async logout() {
    await logoutRequest();
    stopRealtime();
    await wipeCache();
    queryClient.clear();
    set({ status: 'anon', user: null, roles: [], isAdmin: false });
  },
}));

setUnauthorizedHandler(() => useAuthStore.setState({ status: 'anon' }));
