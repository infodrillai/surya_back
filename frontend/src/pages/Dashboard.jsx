import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { useLiveQuery } from 'dexie-react-hooks';
import { getList } from '../api/client';
import { db } from '../db/dexie';
import { useFinishedCost } from '../hooks/useFinishedCost';
import { fmtMoney, fmtNum } from '../lib/format';
import { useAuthStore } from '../stores/authStore';

const Stat = ({ label, value, note }) => (
  <Paper variant="outlined" sx={{ p: 2.5 }}>
    <Typography variant="body2" color="text.secondary">{label}</Typography>
    <Typography variant="h5" sx={{ mt: 0.5 }}>{value}</Typography>
    {note}
  </Paper>
);

export default function Dashboard() {
  const { fullName, isAdmin, hasRole } = useAuthStore();
  const products = useLiveQuery(() => db.Product.toArray(), []) || [];
  const finished = useFinishedCost().data || {};
  const pending = useQuery({ queryKey: ['list', 'Sales Order'], queryFn: () => getList('Sales Order'), enabled: isAdmin || hasRole(['CS Sales']) });
  const finishedRows = Object.entries(finished);
  const value = finishedRows.reduce((s, [, r]) => s + r.stock * r.unit_price, 0);
  const low = finishedRows.filter(([code, r]) => r.stock < (products.find((p) => p.name === code)?.low_stock_limit || 0));
  const waiting = (pending.data || []).filter((o) => o.status === 'Pending Approval').length;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5">Welcome, {fullName}</Typography>
        <Typography color="text.secondary">Here is where stock and orders stand today.</Typography>
      </Box>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
        <Stat label="Products" value={fmtNum(products.length, 0)} />
        <Stat label="Finished stock value" value={fmtMoney(value)} />
        <Stat label="Finished below low limit" value={fmtNum(low.length, 0)} note={low.length > 0 && <Chip size="small" color="warning" label="Needs production" sx={{ mt: 1 }} />} />
        <Stat label="Orders awaiting approval" value={fmtNum(waiting, 0)} />
      </Box>
    </Stack>
  );
}
