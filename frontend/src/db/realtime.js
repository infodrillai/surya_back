import { io } from 'socket.io-client';
import { reloadMasters, syncMasters } from './masterCache';

let socket = null;
let detach = () => {};

/** Live invalidation. Focus + reconnect re-run the version check in case the socket dropped. */
export function startRealtime() {
  stopRealtime();
  const site = import.meta.env.VITE_SITE_NAME || 'clssurya.local';
  socket = io(`/${site}`, { withCredentials: true, transports: ['websocket', 'polling'] });
  socket.on('masters_changed', ({ doctype }) => reloadMasters([doctype]).catch(() => syncMasters()));
  socket.io.on('reconnect', syncMasters);
  const onFocus = () => syncMasters();
  window.addEventListener('focus', onFocus);
  detach = () => window.removeEventListener('focus', onFocus);
}

export function stopRealtime() {
  detach();
  socket?.disconnect();
  socket = null;
}
