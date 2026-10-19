import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import EditIcon from '@mui/icons-material/EditOutlined';
import SearchIcon from '@mui/icons-material/Search';
import VisibilityIcon from '@mui/icons-material/VisibilityOutlined';
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton, InputAdornment,
  Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography,
} from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLiveQuery } from 'dexie-react-hooks';
import { useMemo, useState } from 'react';
import { deleteDoc, getDoc, getList, runAction } from '../api/client';
import { db } from '../db/dexie';
import { reloadMasters } from '../db/masterCache';
import { fmtDate, fmtMoney, fmtNum } from '../lib/format';
import { useAuthStore } from '../stores/authStore';
import { useUiStore } from '../stores/uiStore';
import DocForm from './DocForm';

const STATUS_COLOR = { Approved: 'info', 'Partially Dispatched': 'warning', Completed: 'success', Accepted: 'success', Rejected: 'error', Superseded: 'default', Sent: 'info' };

function Cell({ col, row }) {
  const v = row[col.field];
  if (col.type === 'doc-status')
    return <Chip size="small" color={row.is_completed ? 'success' : 'default'} label={row.is_completed ? 'Completed' : 'Draft'} />;
  if (col.type === 'status') return <Chip size="small" color={STATUS_COLOR[v] || 'default'} variant={v === 'Pending Approval' ? 'outlined' : 'filled'} label={v} />;
  if (col.type === 'currency') return fmtMoney(v, col.dp ?? 2);
  if (col.type === 'number') return fmtNum(v, col.dp ?? 3);
  if (col.type === 'date') return fmtDate(v);
  if (col.type === 'flag') return v ? <Chip size="small" color="warning" label="Below cost" /> : null;
  return v ?? '';
}

/** List + add / edit / delete for one resource. Masters read from IndexedDB, transactions from the server. */
export default function CrudPage({ config, embedded = false }) {
  const qc = useQueryClient();
  const notify = useUiStore((s) => s.notify);
  const isAdmin = useAuthStore((s) => s.isAdmin);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(10);
  const [editing, setEditing] = useState(null); // null | {} (new) | doc
  const [deleting, setDeleting] = useState(null);

  const cached = useLiveQuery(() => (config.master ? db.table(config.doctype).toArray() : []), [config.doctype]);
  const server = useQuery({ queryKey: ['list', config.doctype], queryFn: () => getList(config.doctype), enabled: !config.master });
  const rows = useMemo(() => {
    const all = (config.master ? [...(cached || [])].sort((a, b) => String(b.modified).localeCompare(String(a.modified))) : server.data) || [];
    const q = search.trim().toLowerCase();
    return q ? all.filter((r) => config.columns.some((c) => String(r[c.field] ?? '').toLowerCase().includes(q))) : all;
  }, [cached, server.data, search, config]);

  const refresh = async () => {
    await qc.invalidateQueries();
    if (config.master) await reloadMasters([config.doctype, ...(config.companion ? [config.companion.doctype] : [])]);
  };

  const remove = useMutation({
    mutationFn: async (name) => {
      if (config.companion && (await db.table(config.companion.doctype).get(name))) await deleteDoc(config.companion.doctype, name);
      return deleteDoc(config.doctype, name);
    },
    onSuccess: async () => { await refresh(); notify('Deleted'); setDeleting(null); },
    onError: (e) => { notify(e.message, 'error'); setDeleting(null); },
  });
  const action = useMutation({
    mutationFn: ({ row, a }) => a.run(row),
    onSuccess: async (msg) => { await refresh(); notify(msg || 'Done'); },
    onError: (e) => notify(e.message, 'error'),
  });

  const openRow = async (row) => setEditing(config.master ? { ...row, ...(config.companion ? await config.companion.load(row) : {}) } : await getDoc(config.doctype, row.name));
  const isLocked = (r) => !!r.is_completed || !!config.isLocked?.(r);
  const pageRows = rows.slice(page * perPage, page * perPage + perPage);

  return (
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2.5, alignItems: { sm: 'center' }, justifyContent: 'space-between' }}>
        <Box>
          {!embedded && <Typography variant="h5">{config.plural || `${config.title}s`}</Typography>}
          {config.subtitle && !embedded && <Typography variant="body2" color="text.secondary">{config.subtitle}</Typography>}
        </Box>
        <Stack direction="row" spacing={1.5}>
          <TextField placeholder="Search" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} sx={{ width: 240, bgcolor: 'background.paper' }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          {!config.readOnlyList && <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditing({})}>Add {config.title}</Button>}
        </Stack>
      </Stack>

      <Paper variant="outlined">
        <TableContainer>
          <Table size="medium">
            <TableHead>
              <TableRow>
                {config.columns.map((c) => <TableCell key={c.field} align={['currency', 'number'].includes(c.type) ? 'right' : 'left'}>{c.label}</TableCell>)}
                {!config.readOnlyList && <TableCell align="right">Actions</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {pageRows.map((row) => {
                const locked = isLocked(row);
                return (
                  <TableRow key={row.name} hover>
                    {config.columns.map((c) => (
                      <TableCell key={c.field} align={['currency', 'number'].includes(c.type) ? 'right' : 'left'}><Cell col={c} row={row} /></TableCell>
                    ))}
                    {!config.readOnlyList && (
                      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                        {(config.rowActions || []).filter((a) => a.show(row, isAdmin)).map((a) => (
                          <Button key={a.key} size="small" sx={{ mr: 0.5 }} disabled={action.isPending} onClick={() => action.mutate({ row, a })}>{a.label}</Button>
                        ))}
                        <Tooltip title={locked ? 'View' : 'Edit'}>
                          <IconButton size="small" onClick={() => openRow(row)} aria-label={locked ? 'View' : 'Edit'}>{locked ? <VisibilityIcon fontSize="small" /> : <EditIcon fontSize="small" />}</IconButton>
                        </Tooltip>
                        <Tooltip title={locked ? 'Locked' : 'Delete'}>
                          <span><IconButton size="small" color="error" disabled={locked} onClick={() => setDeleting(row)} aria-label="Delete"><DeleteIcon fontSize="small" /></IconButton></span>
                        </Tooltip>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
              {pageRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={config.columns.length + 1} sx={{ py: 6, textAlign: 'center' }}>
                    <Typography color="text.secondary">{search ? 'Nothing matches your search.' : config.readOnlyList ? 'Nothing here yet.' : `No ${config.plural?.toLowerCase() || config.title.toLowerCase() + 's'} yet. Use “Add ${config.title}” to create the first one.`}</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination component="div" count={rows.length} page={page} rowsPerPage={perPage} rowsPerPageOptions={[10, 25, 50]}
          onPageChange={(_, p) => setPage(p)} onRowsPerPageChange={(e) => { setPerPage(+e.target.value); setPage(0); }} />
      </Paper>

      {editing && <DocForm config={config} doc={editing.name ? editing : null} open onClose={() => setEditing(null)} />}

      <Dialog open={!!deleting} onClose={() => setDeleting(null)}>
        <DialogTitle>Delete {config.title}?</DialogTitle>
        <DialogContent><DialogContentText>“{deleting?.name}” will be permanently removed. This cannot be undone.</DialogContentText></DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)}>Cancel</Button>
          <Button color="error" variant="contained" disabled={remove.isPending} onClick={() => remove.mutate(deleting.name)}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}