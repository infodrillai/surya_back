import { create } from 'zustand';

export const useUiStore = create((set) => ({
  mobileNav: false,
  toast: null, // { message, severity }
  setMobileNav: (mobileNav) => set({ mobileNav }),
  notify: (message, severity = 'success') => set({ toast: { message, severity, key: Date.now() } }),
  clearToast: () => set({ toast: null }),
}));
