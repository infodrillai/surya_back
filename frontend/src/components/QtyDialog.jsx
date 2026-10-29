import React, { useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';

/**
 * QtyDialog
 *
 * Props:
 *  open        – boolean
 *  onClose     – () => void
 *  orderId     – string (Sales Order name)
 *  pendingItems – [{ order_item, product, ordered_qty, already_dispatched, pending_qty }]
 *  onSubmit    – async (items: [{order_item, quantity}]) => string  (returns result message)
 */
export default function QtyDialog({ open, onClose, orderId, pendingItems = [], onSubmit }) {
  const [qtys, setQtys] = useState(() => buildDefault(pendingItems));
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState('');

  // Re-initialise when pendingItems changes (dialog re-opens for a new order)
  React.useEffect(() => {
    setQtys(buildDefault(pendingItems));
    setErrors({});
    setApiError('');
  }, [pendingItems, open]);

  function buildDefault(items) {
    return Object.fromEntries(items.map((i) => [i.order_item, String(i.pending_qty ?? 0)]));
  }

  function handleChange(orderItem, value, pendingQty) {
    setQtys((prev) => ({ ...prev, [orderItem]: value }));
    // live validation
    const num = Number(value);
    if (value === '' || isNaN(num) || num < 0) {
      setErrors((prev) => ({ ...prev, [orderItem]: 'Enter a valid number ≥ 0' }));
    } else if (num > pendingQty) {
      setErrors((prev) => ({ ...prev, [orderItem]: `Max ${pendingQty}` }));
    } else {
      setErrors((prev) => { const n = { ...prev }; delete n[orderItem]; return n; });
    }
  }

  async function handleSubmit() {
    // Final validation
    const newErrors = {};
    let atLeastOne = false;
    for (const item of pendingItems) {
      const val = Number(qtys[item.order_item]);
      if (isNaN(val) || val < 0) {
        newErrors[item.order_item] = 'Enter a valid number ≥ 0';
      } else if (val > item.pending_qty) {
        newErrors[item.order_item] = `Max ${item.pending_qty}`;
      } else if (val > 0) {
        atLeastOne = true;
      }
    }
    if (Object.keys(newErrors).length) { setErrors(newErrors); return; }
    if (!atLeastOne) { setApiError('Enter a quantity > 0 for at least one item.'); return; }

    setSubmitting(true);
    setApiError('');
    try {
      const items = pendingItems
        .map((i) => ({ order_item: i.order_item, quantity: Number(qtys[i.order_item]) }))
        .filter((i) => i.quantity > 0);
      const msg = await onSubmit(items);
      onClose(msg);
    } catch (err) {
      setApiError(err?.message || 'An error occurred. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={() => onClose(null)} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Stack>
          <Typography variant="h6" fontWeight={700}>Add Dispatch</Typography>
          {orderId && (
            <Typography variant="caption" color="text.secondary">
              Sales Order: {orderId}
            </Typography>
          )}
        </Stack>
        <IconButton onClick={() => onClose(null)} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {apiError && <Alert severity="error" sx={{ mb: 2 }}>{apiError}</Alert>}

        {pendingItems.length === 0 ? (
          <Alert severity="info">No pending items to dispatch.</Alert>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow sx={{ '& th': { fontWeight: 700 } }}>
                <TableCell>Product</TableCell>
                <TableCell align="right">Ordered</TableCell>
                <TableCell align="right">Already Dispatched</TableCell>
                <TableCell align="right">Pending</TableCell>
                <TableCell align="right" sx={{ minWidth: 150 }}>Dispatch Now</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {pendingItems.map((item) => (
                <TableRow key={item.order_item} hover>
                  <TableCell>{item.product}</TableCell>
                  <TableCell align="right">{item.ordered_qty}</TableCell>
                  <TableCell align="right">{item.already_dispatched}</TableCell>
                  <TableCell align="right">{item.pending_qty}</TableCell>
                  <TableCell align="right">
                    <TextField
                      size="small"
                      type="number"
                      value={qtys[item.order_item] ?? ''}
                      onChange={(e) => handleChange(item.order_item, e.target.value, item.pending_qty)}
                      error={!!errors[item.order_item]}
                      helperText={errors[item.order_item]}
                      inputProps={{ min: 0, max: item.pending_qty, step: 1 }}
                      InputProps={{
                        endAdornment: (
                          <InputAdornment position="end">
                            <Typography variant="caption" color="text.secondary">
                              / {item.pending_qty}
                            </Typography>
                          </InputAdornment>
                        ),
                      }}
                      sx={{ width: 150 }}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={() => onClose(null)} disabled={submitting} color="inherit">
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={submitting || pendingItems.length === 0}
          variant="contained"
          color="primary"
        >
          {submitting ? 'Creating…' : 'Create Dispatch'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
