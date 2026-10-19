import LogoutIcon from '@mui/icons-material/LogoutOutlined';
import MenuIcon from '@mui/icons-material/Menu';
import SpaceDashboardIcon from '@mui/icons-material/SpaceDashboardOutlined';
import SyncIcon from '@mui/icons-material/Sync';
import {
  AppBar, Avatar, Box, Chip, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Tooltip, Typography, useMediaQuery,
} from '@mui/material';
import { NavLink, useLocation } from 'react-router-dom';
import { MENU } from '../config/menu';
import { useAuthStore } from '../stores/authStore';
import { useSyncStore } from '../stores/syncStore';
import { useUiStore } from '../stores/uiStore';
import { palette } from '../theme';

const WIDTH = 252;

function Nav({ onNavigate }) {
  const hasRole = useAuthStore((s) => s.hasRole);
  const { pathname } = useLocation();
  const item = (to, label, Icon) => (
    <ListItemButton key={to} component={NavLink} to={to} onClick={onNavigate} selected={pathname === to || (to !== '/' && pathname.startsWith(to))}
      sx={{ mx: 1.5, mb: 0.25, borderRadius: 2, color: '#c5d6d3', '&.Mui-selected': { bgcolor: palette.teal, color: '#fff' }, '&.Mui-selected:hover': { bgcolor: palette.teal }, '&:hover': { bgcolor: palette.inkSoft } }}>
      <ListItemIcon sx={{ color: 'inherit', minWidth: 38 }}><Icon fontSize="small" /></ListItemIcon>
      <ListItemText primary={label} slotProps={{ primary: { fontSize: 14.5 } }} />
    </ListItemButton>
  );
  return (
    <Box sx={{ height: '100%', bgcolor: palette.ink, color: '#fff', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ px: 3, py: 2.5 }}>
        <Typography variant="h6" sx={{ lineHeight: 1.1 }}>CLS Surya</Typography>
        <Typography variant="caption" sx={{ color: '#88a7a2' }}>Production and sales</Typography>
      </Box>
      <Box sx={{ flex: 1, overflowY: 'auto', pb: 2 }}>
        <List dense disablePadding>{item('/', 'Dashboard', SpaceDashboardIcon)}</List>
        {MENU.map((g) => {
          const items = g.items.filter((i) => hasRole(i.roles));
          return items.length ? (
            <List key={g.section} dense subheader={<Typography variant="caption" sx={{ px: 3, pt: 2, pb: 0.5, display: 'block', color: '#6f918c' }}>{g.section}</Typography>}>
              {items.map((i) => item(i.path, i.label, i.icon))}
            </List>
          ) : null;
        })}
      </Box>
    </Box>
  );
}

export default function Layout({ children }) {
  const wide = useMediaQuery((t) => t.breakpoints.up('md'));
  const { mobileNav, setMobileNav } = useUiStore();
  const { fullName, user, logout, roles, isAdmin } = useAuthStore();
  const sync = useSyncStore();
  const role = isAdmin ? 'Admin' : (roles.find((r) => r.startsWith('CS ')) || '').replace('CS ', '');

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Drawer variant={wide ? 'permanent' : 'temporary'} open={wide || mobileNav} onClose={() => setMobileNav(false)}
        sx={{ width: WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: WIDTH, border: 0 } }}>
        <Nav onNavigate={() => setMobileNav(false)} />
      </Drawer>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: 'rgba(243,246,245,.9)', backdropFilter: 'blur(6px)' }}>
          <Toolbar sx={{ gap: 1.5 }}>
            {!wide && <IconButton edge="start" onClick={() => setMobileNav(true)} aria-label="Open menu"><MenuIcon /></IconButton>}
            <Box sx={{ flex: 1 }} />
            <Tooltip title={sync.error || 'Master data cache'}>
              <Chip size="small" icon={<SyncIcon />} variant="outlined" color={sync.status === 'error' ? 'error' : sync.status === 'ready' ? 'success' : 'default'}
                label={sync.status === 'ready' ? 'Up to date' : sync.status === 'error' ? 'Sync problem' : 'Syncing'} />
            </Tooltip>
            <Divider orientation="vertical" flexItem />
            <Avatar sx={{ width: 32, height: 32, bgcolor: palette.teal, fontSize: 14 }}>{(fullName || user || '?')[0]}</Avatar>
            <Box sx={{ display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>{fullName || user}</Typography>
              <Typography variant="caption" color="text.secondary">{role}</Typography>
            </Box>
            <Tooltip title="Sign out"><IconButton onClick={logout} aria-label="Sign out"><LogoutIcon /></IconButton></Tooltip>
          </Toolbar>
        </AppBar>
        <Box component="main" sx={{ p: { xs: 2, md: 4 }, maxWidth: 1400 }}>{children}</Box>
      </Box>
    </Box>
  );
}
