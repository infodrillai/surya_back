import { createTheme } from '@mui/material/styles';

// Ink-green sidebar, quiet paper content area, teal accent, amber reserved for warnings.
export const palette = { ink: '#0e2a2f', inkSoft: '#17383e', teal: '#0f766e', paper: '#f3f6f5', line: '#dde5e3' };

export const theme = createTheme({
  palette: {
    primary: { main: palette.teal },
    secondary: { main: '#b45309' },
    background: { default: palette.paper, paper: '#ffffff' },
    text: { primary: '#12262a', secondary: '#52666a' },
    divider: palette.line,
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Segoe UI", "Helvetica Neue", Roboto, system-ui, sans-serif',
    h5: { fontWeight: 700, letterSpacing: '-0.01em' },
    h6: { fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 650, color: '#3b5156', background: '#eef3f2', whiteSpace: 'nowrap' } } },
    MuiTextField: { defaultProps: { size: 'small', fullWidth: true } },
  },
});
