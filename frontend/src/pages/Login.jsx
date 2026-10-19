import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { palette } from '../theme';

export default function Login() {
  const login = useAuthStore((s) => s.login);
  const [usr, setUsr] = useState('');
  const [pwd, setPwd] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try { await login(usr, pwd); } catch (err) { setError(err.message || 'Sign in failed'); } finally { setBusy(false); }
  };

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: palette.ink, p: 2 }}>
      <Paper component="form" onSubmit={submit} sx={{ p: 4, width: 380, maxWidth: '100%' }}>
        <Typography variant="h5">CLS Surya</Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>Sign in to manage production and sales.</Typography>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Email or username" value={usr} onChange={(e) => setUsr(e.target.value)} autoFocus autoComplete="username" />
          <TextField label="Password" type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} autoComplete="current-password" />
          <Button type="submit" variant="contained" size="large" disabled={busy || !usr || !pwd}>Sign in</Button>
        </Stack>
      </Paper>
    </Box>
  );
}
