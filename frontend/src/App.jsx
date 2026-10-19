import { Alert, Box, CircularProgress, Snackbar, Typography } from '@mui/material';
import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import CrudPage from './components/CrudPage';
import { RESOURCES } from './config/resources';
import { MENU } from './config/menu';
import { prepareCache, syncMasters } from './db/masterCache';
import { startRealtime, stopRealtime } from './db/realtime';
import BatchPage from './pages/BatchPage';
import CustomerOutstandingPage from './pages/CustomerOutstandingPage';
import Dashboard from './pages/Dashboard';
import InventoryPage from './pages/InventoryPage';
import Login from './pages/Login';
import { useAuthStore } from './stores/authStore';
import { useSyncStore } from './stores/syncStore';
import { useUiStore } from './stores/uiStore';

const ROLES_BY_PATH = Object.fromEntries(MENU.flatMap((g) => g.items.map((i) => [i.path, i.roles])));

function Guard({ path, children }) {
  return useAuthStore.getState().hasRole(ROLES_BY_PATH[path]) ? children : <Navigate to="/" replace />;
}

function Loading({ text }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <Box sx={{ textAlign: 'center' }}><CircularProgress /><Typography sx={{ mt: 2 }} color="text.secondary">{text}</Typography></Box>
    </Box>
  );
}

function Shell() {
  const user = useAuthStore((s) => s.user);
  const status = useSyncStore((s) => s.status);

  useEffect(() => {
    let live = true;
    (async () => {
      await prepareCache(user); // different user or schema bump -> wipe IndexedDB
      if (!live) return;
      await syncMasters();
      startRealtime();
    })();
    return () => { live = false; stopRealtime(); };
  }, [user]);

  if (status === 'idle' || (status === 'syncing' && !Object.keys(useSyncStore.getState().versions).length)) return <Loading text="Loading master data…" />;

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {Object.entries(RESOURCES).map(([path, config]) => (
          <Route key={path} path={path} element={<Guard path={path}><CrudPage key={path} config={config} /></Guard>} />
        ))}
        <Route path="/inventory" element={<Guard path="/inventory"><InventoryPage /></Guard>} />
        <Route path="/batch" element={<Guard path="/batch"><BatchPage /></Guard>} />
        <Route path="/customer-outstanding" element={<Guard path="/customer-outstanding"><CustomerOutstandingPage /></Guard>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}


export default function App() {
  const { status, bootstrap } = useAuthStore();
  const { toast, clearToast } = useUiStore();
  useEffect(() => { bootstrap(); }, [bootstrap]);

  return (
    <>
      {status === 'loading' ? <Loading text="Starting…" /> : status === 'anon' ? <Login /> : <Shell />}
      <Snackbar key={toast?.key} open={!!toast} autoHideDuration={4500} onClose={clearToast} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        {toast ? <Alert severity={toast.severity} variant="filled" onClose={clearToast} sx={{ whiteSpace: 'pre-line' }}>{toast.message}</Alert> : undefined}
      </Snackbar>
    </>
  );
}
