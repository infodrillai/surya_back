import React, { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  TextField,
  InputAdornment,
  MenuItem,
  Button,
  IconButton,
  Tooltip,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  ToggleButtonGroup,
  ToggleButton,
  CircularProgress,
  Alert,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Stack,
  LinearProgress,
  Collapse,
} from '@mui/material';

import SearchRounded from '@mui/icons-material/SearchRounded';
import CloseRounded from '@mui/icons-material/CloseRounded';
import SyncRounded from '@mui/icons-material/SyncRounded';
import FileDownloadOutlined from '@mui/icons-material/FileDownloadOutlined';
import PeopleAltOutlined from '@mui/icons-material/PeopleAltOutlined';
import BusinessOutlined from '@mui/icons-material/BusinessOutlined';
import AccountBalanceWalletOutlined from '@mui/icons-material/AccountBalanceWalletOutlined';
import TrendingUpRounded from '@mui/icons-material/TrendingUpRounded';
import TrendingDownRounded from '@mui/icons-material/TrendingDownRounded';
import AccessTimeOutlined from '@mui/icons-material/AccessTimeOutlined';
import TableChartOutlined from '@mui/icons-material/TableChartOutlined';
import ViewAgendaOutlined from '@mui/icons-material/ViewAgendaOutlined';
import RefreshRounded from '@mui/icons-material/RefreshRounded';
import CheckCircleOutlineRounded from '@mui/icons-material/CheckCircleOutlineRounded';
import ErrorOutlineRounded from '@mui/icons-material/ErrorOutlineRounded';
import HelpOutlineRounded from '@mui/icons-material/HelpOutlineRounded';
import FilterAltOutlined from '@mui/icons-material/FilterAltOutlined';

import { call } from '../api/client';
import { fmtMoney, fmtNum } from '../lib/format';
import { palette } from '../theme';

const AGEING_BUCKETS = [
  { key: 'age_0_30', label: '0 - 30 Days', short: '0-30d', color: '#10b981', lightBg: 'rgba(16, 185, 129, 0.12)', border: '#6ee7b7' },
  { key: 'age_30_60', label: '30 - 60 Days', short: '30-60d', color: '#0d9488', lightBg: 'rgba(13, 148, 136, 0.12)', border: '#5eead4' },
  { key: 'age_60_90', label: '60 - 90 Days', short: '60-90d', color: '#0284c7', lightBg: 'rgba(2, 132, 199, 0.12)', border: '#7dd3fc' },
  { key: 'age_90_120', label: '90 - 120 Days', short: '90-120d', color: '#6366f1', lightBg: 'rgba(99, 102, 241, 0.12)', border: '#a5b4fc' },
  { key: 'age_120_150', label: '120 - 150 Days', short: '120-150d', color: '#f59e0b', lightBg: 'rgba(245, 158, 11, 0.12)', border: '#fcd34d' },
  { key: 'age_150_180', label: '150 - 180 Days', short: '150-180d', color: '#ea580c', lightBg: 'rgba(234, 88, 12, 0.12)', border: '#fdba74' },
  { key: 'age_180_above', label: '180+ Days', short: '180d+', color: '#e11d48', lightBg: 'rgba(225, 29, 72, 0.12)', border: '#fda4af' },
];

export default function CustomerOutstandingPage() {
  const queryClient = useQueryClient();

  // Filters & Page State
  const [selectedCompany, setSelectedCompany] = useState('__ALL__');
  const [balanceFilter, setBalanceFilter] = useState('ALL'); // 'ALL', 'Dr', 'Cr', 'Zero'
  const [ageingFilter, setAgeingFilter] = useState('ALL'); // 'ALL' or specific bucket key
  const [tableViewMode, setTableViewMode] = useState('AGEING'); // 'AGEING' or 'OVERVIEW'
  const [searchText, setSearchText] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [showCompaniesGrid, setShowCompaniesGrid] = useState(true);

  // Sync Modal State
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  const [tallyUrl, setTallyUrl] = useState('http://localhost:9000');
  const [targetCompany, setTargetCompany] = useState('__ALL__');
  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [showHelp, setShowHelp] = useState(false);

  // Query Dashboard Data
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['customerOutstandingsDashboard', selectedCompany],
    queryFn: async () => {
      const res = await call(
        'clssurya.api.get_customer_outstandings_dashboard',
        { company: selectedCompany !== '__ALL__' ? selectedCompany : undefined },
        { get: true }
      );
      return res;
    },
    staleTime: 30 * 1000,
  });

  const dashboardData = data || {
    customers: [],
    total_customers: 0,
    total_receivables: 0,
    total_payables: 0,
    net_outstanding: 0,
    gst_registered_count: 0,
    companies: [],
    companies_breakdown: [],
    ageing_summary: {
      age_0_30: 0,
      age_30_60: 0,
      age_60_90: 0,
      age_90_120: 0,
      age_120_150: 0,
      age_150_180: 0,
      age_180_above: 0,
      total: 0,
    },
  };

  // Filtered customer list
  const filteredCustomers = useMemo(() => {
    let list = dashboardData.customers || [];

    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      list = list.filter(
        (c) =>
          (c.customer_name || '').toLowerCase().includes(q) ||
          (c.gstin || '').toLowerCase().includes(q) ||
          (c.phone || '').toLowerCase().includes(q) ||
          (c.city || '').toLowerCase().includes(q) ||
          (c.state || '').toLowerCase().includes(q)
      );
    }

    if (balanceFilter === 'Dr') {
      list = list.filter((c) => (c.net_balance ?? c.total_outstanding ?? 0) > 0);
    } else if (balanceFilter === 'Cr') {
      list = list.filter((c) => (c.net_balance ?? c.total_outstanding ?? 0) < 0 || c.payable_cr > 0);
    } else if (balanceFilter === 'Zero') {
      list = list.filter((c) => (c.net_balance ?? c.total_outstanding ?? 0) === 0);
    }

    if (ageingFilter !== 'ALL') {
      list = list.filter((c) => (c[ageingFilter] || 0) > 0);
    }

    return list;
  }, [dashboardData.customers, searchText, balanceFilter, ageingFilter]);

  const paginatedCustomers = useMemo(() => {
    const start = page * rowsPerPage;
    return filteredCustomers.slice(start, start + rowsPerPage);
  }, [filteredCustomers, page, rowsPerPage]);

  // Test Tally Connection
  const handleTestTally = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await call('clssurya.api.test_tally_connection', { tally_url: tallyUrl });
      setTestResult(res);
      if (res.success && res.companies && res.companies.length > 0) {
        if (!res.companies.includes(targetCompany) && targetCompany !== '__ALL__') {
          setTargetCompany('__ALL__');
        }
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err.message || 'Network request failed',
        companies: [],
      });
    } finally {
      setIsTesting(false);
    }
  };

  // Run Tally Sync
  const handleRunSync = async () => {
    setIsSyncing(true);
    setSyncResult(null);
    try {
      const res = await call('clssurya.api.sync_from_tally', {
        tally_url: tallyUrl,
        company: targetCompany !== '__ALL__' ? targetCompany : null,
      });
      setSyncResult(res);
      queryClient.invalidateQueries({ queryKey: ['customerOutstandingsDashboard'] });
      refetch();
    } catch (err) {
      setSyncResult({
        success: false,
        message: err.message || 'Sync failed',
      });
    } finally {
      setIsSyncing(false);
    }
  };

  // Export CSV
  const handleExportCsv = () => {
    if (!filteredCustomers.length) return;
    const headers = [
      'Customer Name',
      'GSTIN',
      'PAN',
      'Phone',
      'City',
      'State',
      'Receivables (Dr)',
      'Advances (Cr)',
      'Net Balance',
      '0-30 Days',
      '30-60 Days',
      '60-90 Days',
      '90-120 Days',
      '120-150 Days',
      '150-180 Days',
      '180+ Days',
      'Companies Breakdown',
    ];

    const rows = filteredCustomers.map((c) => {
      const compSummary = (c.company_outstandings || [])
        .map((co) => `${co.company_name}: ₹${co.closing_balance} (${co.balance_type})`)
        .join('; ');

      return [
        `"${(c.customer_name || '').replace(/"/g, '""')}"`,
        `"${c.gstin || ''}"`,
        `"${c.pan || ''}"`,
        `"${c.phone || c.mobile || ''}"`,
        `"${c.city || ''}"`,
        `"${c.state || ''}"`,
        c.receivable_dr || 0,
        c.payable_cr || 0,
        c.net_balance ?? c.total_outstanding ?? 0,
        c.age_0_30 || 0,
        c.age_30_60 || 0,
        c.age_60_90 || 0,
        c.age_90_120 || 0,
        c.age_120_150 || 0,
        c.age_150_180 || 0,
        c.age_180_above || 0,
        `"${compSummary.replace(/"/g, '""')}"`,
      ].join(',');
    });

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute(
      'download',
      `customer_outstandings_${selectedCompany !== '__ALL__' ? selectedCompany : 'all_companies'}_${new Date().toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1600, margin: '0 auto' }}>
      {/* Top Banner / Actions */}
      <Paper
        elevation={0}
        sx={{
          p: 3,
          mb: 3,
          borderRadius: 3,
          background: `linear-gradient(135deg, ${palette.ink} 0%, ${palette.inkSoft} 100%)`,
          color: '#ffffff',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          boxShadow: '0 10px 25px -5px rgba(14, 42, 47, 0.25)',
        }}
      >
        <Box>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <AccountBalanceWalletOutlined sx={{ fontSize: 32, color: '#2dd4bf' }} />
            <Typography variant="h5" sx={{ fontWeight: 700, color: '#ffffff' }}>
              Customer Outstanding
            </Typography>
            <Chip
              label={`${dashboardData.total_customers || 0} Customers`}
              size="small"
              sx={{ bgcolor: 'rgba(255,255,255,0.15)', color: '#ffffff', fontWeight: 600 }}
            />
          </Stack>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.75)', mt: 0.5 }}>
            Company-wise accounts receivable, ageing distribution & Tally synchronization
          </Typography>
        </Box>

        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
          {/* Company Selector */}
          <TextField
            select
            size="small"
            value={selectedCompany}
            onChange={(e) => {
              setSelectedCompany(e.target.value);
              setPage(0);
            }}
            sx={{
              minWidth: 200,
              bgcolor: 'rgba(255,255,255,0.12)',
              borderRadius: 2,
              '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.2)' },
              '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.4)' },
              '& .MuiSelect-select': { color: '#ffffff', py: 0.9, fontWeight: 500 },
              '& .MuiSvgIcon-root': { color: '#ffffff' },
            }}
          >
            <MenuItem value="__ALL__">All Companies ({dashboardData.companies?.length || 0})</MenuItem>
            {(dashboardData.companies || []).map((comp) => (
              <MenuItem key={comp} value={comp}>
                {comp}
              </MenuItem>
            ))}
          </TextField>

          {/* Sync with Tally Button */}
          <Button
            variant="contained"
            startIcon={<SyncRounded sx={{ animation: isFetching ? 'spin 1.5s linear infinite' : 'none', '@keyframes spin': { '100%': { transform: 'rotate(360deg)' } } }} />}
            onClick={() => {
              setSyncResult(null);
              setTestResult(null);
              setSyncModalOpen(true);
            }}
            sx={{
              bgcolor: '#14b8a6',
              color: '#042f2e',
              fontWeight: 700,
              '&:hover': { bgcolor: '#2dd4bf' },
              px: 2.5,
              py: 0.9,
              borderRadius: 2,
            }}
          >
            Sync with Tally
          </Button>

          {/* Export CSV */}
          <Button
            variant="outlined"
            startIcon={<FileDownloadOutlined />}
            onClick={handleExportCsv}
            disabled={!filteredCustomers.length}
            sx={{
              color: '#ffffff',
              borderColor: 'rgba(255,255,255,0.3)',
              '&:hover': { borderColor: '#ffffff', bgcolor: 'rgba(255,255,255,0.08)' },
              py: 0.9,
              borderRadius: 2,
            }}
          >
            Export CSV
          </Button>

          {/* Refresh */}
          <Tooltip title="Refresh Dashboard Data">
            <IconButton
              onClick={() => refetch()}
              sx={{ color: '#ffffff', bgcolor: 'rgba(255,255,255,0.1)', '&:hover': { bgcolor: 'rgba(255,255,255,0.2)' } }}
            >
              <RefreshRounded fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Paper>

      {/* KPI Cards */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        {/* Total Customers */}
        <Grid item xs={12} sm={6} md={3}>
          <Card elevation={0} sx={{ borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
            <CardContent sx={{ p: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.05em' }}>
                    Total Customers
                  </Typography>
                  <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.8, color: palette.ink }}>
                    {fmtNum(dashboardData.total_customers, 0)}
                  </Typography>
                </Box>
                <Box sx={{ p: 1.2, borderRadius: 2, bgcolor: '#f0fdf4', color: '#16a34a' }}>
                  <PeopleAltOutlined />
                </Box>
              </Stack>
              <Stack direction="row" spacing={1} sx={{ mt: 1.5 }} alignItems="center">
                <Chip
                  size="small"
                  label={`${dashboardData.gst_registered_count || 0} GST Registered`}
                  sx={{ bgcolor: '#e0f2fe', color: '#0369a1', fontWeight: 600, fontSize: '0.75rem' }}
                />
                <Typography variant="caption" color="text.secondary">
                  {selectedCompany === '__ALL__' ? 'Across all companies' : selectedCompany}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* Total Receivables Dr */}
        <Grid item xs={12} sm={6} md={3}>
          <Card elevation={0} sx={{ borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
            <CardContent sx={{ p: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.05em' }}>
                    Total Receivables (Dr)
                  </Typography>
                  <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.8, color: '#0f766e' }}>
                    {fmtMoney(dashboardData.total_receivables)}
                  </Typography>
                </Box>
                <Box sx={{ p: 1.2, borderRadius: 2, bgcolor: '#f0fdfa', color: '#0f766e' }}>
                  <TrendingUpRounded />
                </Box>
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                Amount due to be collected from customers
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Total Payables Cr (Advances) */}
        <Grid item xs={12} sm={6} md={3}>
          <Card elevation={0} sx={{ borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
            <CardContent sx={{ p: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.05em' }}>
                    Advances / Payables (Cr)
                  </Typography>
                  <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.8, color: '#b45309' }}>
                    {fmtMoney(dashboardData.total_payables)}
                  </Typography>
                </Box>
                <Box sx={{ p: 1.2, borderRadius: 2, bgcolor: '#fffbeb', color: '#b45309' }}>
                  <TrendingDownRounded />
                </Box>
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                Advance payments received from customers
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Net Outstanding */}
        <Grid item xs={12} sm={6} md={3}>
          <Card
            elevation={0}
            sx={{
              borderRadius: 3,
              border: `1px solid ${dashboardData.net_outstanding >= 0 ? '#99f6e4' : '#fed7aa'}`,
              bgcolor: dashboardData.net_outstanding >= 0 ? '#f0fdfa' : '#fff7ed',
            }}
          >
            <CardContent sx={{ p: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                <Box>
                  <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.05em' }}>
                    Net Outstanding
                  </Typography>
                  <Typography
                    variant="h5"
                    sx={{
                      fontWeight: 800,
                      mt: 0.8,
                      color: dashboardData.net_outstanding >= 0 ? '#0f766e' : '#c2410c',
                    }}
                  >
                    {fmtMoney(Math.abs(dashboardData.net_outstanding))}
                  </Typography>
                </Box>
                <Chip
                  label={dashboardData.net_outstanding >= 0 ? 'Dr (Receivable)' : 'Cr (Payable)'}
                  size="small"
                  sx={{
                    fontWeight: 700,
                    bgcolor: dashboardData.net_outstanding >= 0 ? '#ccfbf1' : '#ffedd5',
                    color: dashboardData.net_outstanding >= 0 ? '#0f766e' : '#c2410c',
                  }}
                />
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                Net balance (Receivables − Advances)
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Ageing Buckets Ribbon */}
      <Paper elevation={0} sx={{ p: 2.5, mb: 3, borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.8 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <AccessTimeOutlined sx={{ color: palette.teal }} />
            <Typography variant="subtitle1" sx={{ fontWeight: 700, color: palette.ink }}>
              Overdue Ageing Analysis
            </Typography>
            {ageingFilter !== 'ALL' && (
              <Chip
                size="small"
                label={`Filtering: ${AGEING_BUCKETS.find((b) => b.key === ageingFilter)?.label || ageingFilter}`}
                onDelete={() => setAgeingFilter('ALL')}
                sx={{ bgcolor: '#e0f2fe', color: '#0369a1', fontWeight: 600 }}
              />
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary">
            Click any age bracket to filter customers
          </Typography>
        </Stack>

        <Grid container spacing={1.5}>
          {AGEING_BUCKETS.map((bucket) => {
            const amount = dashboardData.ageing_summary?.[bucket.key] || 0;
            const isSelected = ageingFilter === bucket.key;

            return (
              <Grid item xs={6} sm={4} md={12 / 7} key={bucket.key}>
                <Box
                  onClick={() => setAgeingFilter(isSelected ? 'ALL' : bucket.key)}
                  sx={{
                    p: 1.5,
                    borderRadius: 2.5,
                    border: `1.5px solid ${isSelected ? bucket.color : bucket.border}`,
                    bgcolor: isSelected ? bucket.lightBg : '#fafafa',
                    cursor: 'pointer',
                    transition: 'all 0.18s ease-in-out',
                    transform: isSelected ? 'scale(1.02)' : 'none',
                    boxShadow: isSelected ? `0 4px 12px ${bucket.color}25` : 'none',
                    '&:hover': {
                      bgcolor: bucket.lightBg,
                      borderColor: bucket.color,
                    },
                  }}
                >
                  <Typography variant="caption" sx={{ fontWeight: 700, color: bucket.color, display: 'block' }}>
                    {bucket.label}
                  </Typography>
                  <Typography variant="subtitle2" sx={{ fontWeight: 800, mt: 0.5, color: '#1e293b' }}>
                    {fmtMoney(amount)}
                  </Typography>
                </Box>
              </Grid>
            );
          })}
        </Grid>
      </Paper>

      {/* Company Breakdown Section (Expandable when All Companies selected) */}
      {selectedCompany === '__ALL__' && dashboardData.companies_breakdown?.length > 1 && (
        <Paper elevation={0} sx={{ p: 2.5, mb: 3, borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <BusinessOutlined sx={{ color: palette.teal }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700, color: palette.ink }}>
                Company Breakdown ({dashboardData.companies_breakdown.length} Companies)
              </Typography>
            </Stack>
            <Button
              size="small"
              onClick={() => setShowCompaniesGrid(!showCompaniesGrid)}
              sx={{ color: palette.teal }}
            >
              {showCompaniesGrid ? 'Hide Breakdown' : 'Show Breakdown'}
            </Button>
          </Stack>

          <Collapse in={showCompaniesGrid}>
            <Grid container spacing={2}>
              {dashboardData.companies_breakdown.map((comp) => (
                <Grid item xs={12} sm={6} md={4} key={comp.company_name}>
                  <Card
                    elevation={0}
                    sx={{
                      p: 2,
                      borderRadius: 2.5,
                      border: `1px solid ${palette.line}`,
                      bgcolor: '#f8fafc',
                      '&:hover': { borderColor: palette.teal, bgcolor: '#ffffff' },
                    }}
                  >
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                      <Box>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700, color: palette.ink }}>
                          {comp.company_name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {comp.customer_count} Customer{comp.customer_count !== 1 ? 's' : ''}
                        </Typography>
                      </Box>
                      <Button
                        size="small"
                        onClick={() => setSelectedCompany(comp.company_name)}
                        sx={{ fontSize: '0.7rem', py: 0.2, px: 1, color: palette.teal }}
                      >
                        Filter
                      </Button>
                    </Stack>

                    <Divider sx={{ my: 1 }} />

                    <Stack direction="row" justifyContent="space-between" sx={{ my: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        Receivables (Dr):
                      </Typography>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: '#0f766e' }}>
                        {fmtMoney(comp.receivables)}
                      </Typography>
                    </Stack>
                    <Stack direction="row" justifyContent="space-between" sx={{ my: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        Advances (Cr):
                      </Typography>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: '#b45309' }}>
                        {fmtMoney(comp.payables)}
                      </Typography>
                    </Stack>
                    <Stack direction="row" justifyContent="space-between" sx={{ my: 0.5 }}>
                      <Typography variant="body2" sx={{ fontWeight: 700, color: palette.ink }}>
                        Net Outstanding:
                      </Typography>
                      <Typography variant="body2" sx={{ fontWeight: 800, color: comp.net_amount >= 0 ? '#0f766e' : '#c2410c' }}>
                        {fmtMoney(Math.abs(comp.net_amount))} {comp.net_amount >= 0 ? 'Dr' : 'Cr'}
                      </Typography>
                    </Stack>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Collapse>
        </Paper>
      )}

      {/* Main Table Paper */}
      <Paper elevation={0} sx={{ borderRadius: 3, border: `1px solid ${palette.line}`, bgcolor: '#ffffff', overflow: 'hidden' }}>
        {/* Controls Toolbar */}
        <Box sx={{ p: 2.5, borderBottom: `1px solid ${palette.line}`, bgcolor: '#ffffff' }}>
          <Grid container spacing={2} alignItems="center">
            {/* Search */}
            <Grid item xs={12} sm={6} md={4}>
              <TextField
                placeholder="Search Customer, GSTIN, Phone, City..."
                size="small"
                value={searchText}
                onChange={(e) => {
                  setSearchText(e.target.value);
                  setPage(0);
                }}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchRounded fontSize="small" sx={{ color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                  endAdornment: searchText && (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setSearchText('')}>
                        <CloseRounded fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
            </Grid>

            {/* Balance Filter Toggle */}
            <Grid item xs={12} sm={6} md={4}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                  Balance:
                </Typography>
                <ToggleButtonGroup
                  size="small"
                  value={balanceFilter}
                  exclusive
                  onChange={(_, val) => {
                    if (val) {
                      setBalanceFilter(val);
                      setPage(0);
                    }
                  }}
                  sx={{
                    '& .MuiToggleButton-root': {
                      px: 1.5,
                      py: 0.4,
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      textTransform: 'none',
                    },
                  }}
                >
                  <ToggleButton value="ALL">All ({dashboardData.customers?.length || 0})</ToggleButton>
                  <ToggleButton value="Dr">Dr (Due)</ToggleButton>
                  <ToggleButton value="Cr">Cr (Adv)</ToggleButton>
                  <ToggleButton value="Zero">Zero</ToggleButton>
                </ToggleButtonGroup>
              </Stack>
            </Grid>

            {/* View Mode Toggle */}
            <Grid item xs={12} sm={12} md={4}>
              <Stack direction="row" spacing={1} justifyContent={{ xs: 'flex-start', md: 'flex-end' }} alignItems="center">
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                  View:
                </Typography>
                <ToggleButtonGroup
                  size="small"
                  value={tableViewMode}
                  exclusive
                  onChange={(_, val) => val && setTableViewMode(val)}
                  sx={{
                    '& .MuiToggleButton-root': {
                      px: 1.5,
                      py: 0.4,
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      textTransform: 'none',
                    },
                  }}
                >
                  <ToggleButton value="AGEING">
                    <TableChartOutlined fontSize="small" sx={{ mr: 0.5 }} /> Ageing Buckets
                  </ToggleButton>
                  <ToggleButton value="OVERVIEW">
                    <ViewAgendaOutlined fontSize="small" sx={{ mr: 0.5 }} /> Companies & Info
                  </ToggleButton>
                </ToggleButtonGroup>
              </Stack>
            </Grid>
          </Grid>
        </Box>

        {/* Loading / Error States */}
        {isLoading && (
          <Box sx={{ p: 6, textAlign: 'center' }}>
            <CircularProgress sx={{ color: palette.teal }} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              Loading customer outstandings...
            </Typography>
          </Box>
        )}

        {isError && (
          <Box sx={{ p: 4 }}>
            <Alert severity="error">{error?.message || 'Failed to load customer outstanding data'}</Alert>
          </Box>
        )}

        {/* Table Content */}
        {!isLoading && !isError && (
          <>
            <TableContainer sx={{ maxHeight: 680 }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ minWidth: 200, fontWeight: 700 }}>Customer Name</TableCell>
                    <TableCell sx={{ minWidth: 140 }}>GSTIN</TableCell>
                    <TableCell sx={{ minWidth: 120 }}>Contact</TableCell>

                    {tableViewMode === 'OVERVIEW' ? (
                      <>
                        <TableCell sx={{ minWidth: 110 }}>City / State</TableCell>
                        <TableCell sx={{ minWidth: 240 }}>Company Outstandings</TableCell>
                      </>
                    ) : (
                      <>
                        {AGEING_BUCKETS.map((b) => (
                          <TableCell key={b.key} align="right" sx={{ minWidth: 100, color: b.color, fontWeight: 700 }}>
                            {b.short}
                          </TableCell>
                        ))}
                      </>
                    )}

                    <TableCell align="right" sx={{ minWidth: 140, fontWeight: 700 }}>
                      Net Outstanding
                    </TableCell>
                  </TableRow>
                </TableHead>

                <TableBody>
                  {paginatedCustomers.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={tableViewMode === 'OVERVIEW' ? 6 : 11} sx={{ py: 6, textAlign: 'center' }}>
                        <Typography variant="body1" color="text.secondary" sx={{ fontWeight: 600 }}>
                          No customer outstandings match the selected filters.
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Try clearing filters or click &quot;Sync with Tally&quot; to fetch latest records.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : (
                    paginatedCustomers.map((cust) => {
                      const net = cust.net_balance ?? cust.total_outstanding ?? 0;
                      const isDr = net > 0;
                      const isCr = net < 0;

                      return (
                        <TableRow
                          key={cust.name}
                          hover
                          onClick={() => setSelectedCustomer(cust)}
                          sx={{
                            cursor: 'pointer',
                            '&:hover': { bgcolor: '#f0fdfa !important' },
                          }}
                        >
                          {/* Name */}
                          <TableCell>
                            <Typography variant="body2" sx={{ fontWeight: 700, color: palette.ink }}>
                              {cust.customer_name}
                            </Typography>
                            {cust.company_outstandings?.length > 1 && (
                              <Typography variant="caption" color="text.secondary">
                                {cust.company_outstandings.length} Companies
                              </Typography>
                            )}
                          </TableCell>

                          {/* GSTIN */}
                          <TableCell>
                            {cust.gstin ? (
                              <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 600, color: '#0369a1' }}>
                                {cust.gstin}
                              </Typography>
                            ) : (
                              <Typography variant="caption" color="text.secondary">
                                —
                              </Typography>
                            )}
                          </TableCell>

                          {/* Contact */}
                          <TableCell>
                            <Typography variant="body2" sx={{ fontSize: '0.82rem' }}>
                              {cust.phone || cust.mobile || '—'}
                            </Typography>
                          </TableCell>

                          {tableViewMode === 'OVERVIEW' ? (
                            <>
                              {/* City / State */}
                              <TableCell>
                                <Typography variant="caption" sx={{ display: 'block', fontWeight: 500 }}>
                                  {cust.city || '—'}
                                </Typography>
                                <Typography variant="caption" color="text.secondary">
                                  {cust.state || ''}
                                </Typography>
                              </TableCell>

                              {/* Company Outstandings chips */}
                              <TableCell>
                                <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap sx={{ py: 0.5 }}>
                                  {(cust.company_outstandings || []).map((co, idx) => (
                                    <Chip
                                      key={idx}
                                      size="small"
                                      label={`${co.company_name}: ${fmtMoney(co.closing_balance)} ${co.balance_type}`}
                                      sx={{
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        bgcolor: co.balance_type === 'Cr' ? '#fffbeb' : '#f0fdfa',
                                        color: co.balance_type === 'Cr' ? '#b45309' : '#0f766e',
                                        border: `1px solid ${co.balance_type === 'Cr' ? '#fde68a' : '#ccfbf1'}`,
                                      }}
                                    />
                                  ))}
                                </Stack>
                              </TableCell>
                            </>
                          ) : (
                            <>
                              {/* Ageing Columns */}
                              {AGEING_BUCKETS.map((b) => {
                                const val = cust[b.key] || 0;
                                return (
                                  <TableCell key={b.key} align="right">
                                    {val > 0 ? (
                                      <Typography variant="body2" sx={{ fontWeight: 600, color: b.color, fontSize: '0.82rem' }}>
                                        {fmtMoney(val)}
                                      </Typography>
                                    ) : (
                                      <Typography variant="caption" color="text.disabled">
                                        —
                                      </Typography>
                                    )}
                                  </TableCell>
                                );
                              })}
                            </>
                          )}

                          {/* Net Outstanding */}
                          <TableCell align="right">
                            <Stack direction="row" spacing={1} justifyContent="flex-end" alignItems="center">
                              <Typography
                                variant="body2"
                                sx={{
                                  fontWeight: 800,
                                  color: isDr ? '#0f766e' : isCr ? '#c2410c' : 'text.secondary',
                                }}
                              >
                                {fmtMoney(Math.abs(net))}
                              </Typography>
                              <Chip
                                size="small"
                                label={isDr ? 'Dr' : isCr ? 'Cr' : 'Zero'}
                                sx={{
                                  height: 20,
                                  fontSize: '0.7rem',
                                  fontWeight: 700,
                                  bgcolor: isDr ? '#ccfbf1' : isCr ? '#ffedd5' : '#f1f5f9',
                                  color: isDr ? '#0f766e' : isCr ? '#c2410c' : '#64748b',
                                }}
                              />
                            </Stack>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </TableContainer>

            {/* Pagination */}
            <TablePagination
              component="div"
              count={filteredCustomers.length}
              page={page}
              onPageChange={(_, newPage) => setPage(newPage)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(parseInt(e.target.value, 10));
                setPage(0);
              }}
              rowsPerPageOptions={[10, 25, 50, 100]}
              sx={{ borderTop: `1px solid ${palette.line}` }}
            />
          </>
        )}
      </Paper>

      {/* Customer Detail Dialog */}
      <Dialog
        open={!!selectedCustomer}
        onClose={() => setSelectedCustomer(null)}
        maxWidth="md"
        fullWidth
        PaperProps={{ sx: { borderRadius: 3 } }}
      >
        {selectedCustomer && (
          <>
            <DialogTitle sx={{ pb: 1, bgcolor: palette.ink, color: '#ffffff' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 700, color: '#ffffff' }}>
                    {selectedCustomer.customer_name}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.7)' }}>
                    Company-wise Outstandings & Profile
                  </Typography>
                </Box>
                <IconButton onClick={() => setSelectedCustomer(null)} sx={{ color: '#ffffff' }}>
                  <CloseRounded />
                </IconButton>
              </Stack>
            </DialogTitle>

            <DialogContent sx={{ p: 3 }}>
              {/* Contact & Meta Grid */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={4}>
                  <Typography variant="caption" color="text.secondary">GSTIN</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{selectedCustomer.gstin || '—'}</Typography>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Typography variant="caption" color="text.secondary">PAN</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{selectedCustomer.pan || '—'}</Typography>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Typography variant="caption" color="text.secondary">Phone / Mobile</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{selectedCustomer.phone || selectedCustomer.mobile || '—'}</Typography>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Typography variant="caption" color="text.secondary">City & State</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {[selectedCustomer.city, selectedCustomer.state].filter(Boolean).join(', ') || '—'}
                  </Typography>
                </Grid>
                <Grid item xs={12} sm={8}>
                  <Typography variant="caption" color="text.secondary">Address</Typography>
                  <Typography variant="body2">{selectedCustomer.address || '—'}</Typography>
                </Grid>
              </Grid>

              <Divider sx={{ my: 2 }} />

              {/* Company Outstandings Child Table */}
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: palette.ink, mb: 1.5 }}>
                Outstandings by Company ({selectedCustomer.company_outstandings?.length || 0})
              </Typography>

              <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 700 }}>Company</TableCell>
                      <TableCell align="right">Opening Bal</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>Closing Bal</TableCell>
                      <TableCell align="center">Type</TableCell>
                      <TableCell align="right">0-30d</TableCell>
                      <TableCell align="right">30-60d</TableCell>
                      <TableCell align="right">60-90d</TableCell>
                      <TableCell align="right">90d+</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(selectedCustomer.company_outstandings || []).map((row, idx) => {
                      const older90 =
                        (row.age_90_120 || 0) +
                        (row.age_120_150 || 0) +
                        (row.age_150_180 || 0) +
                        (row.age_180_above || 0);

                      return (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontWeight: 600 }}>{row.company_name}</TableCell>
                          <TableCell align="right">{fmtMoney(row.opening_balance)}</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700, color: row.balance_type === 'Dr' ? '#0f766e' : '#b45309' }}>
                            {fmtMoney(row.closing_balance)}
                          </TableCell>
                          <TableCell align="center">
                            <Chip
                              size="small"
                              label={row.balance_type || 'Dr'}
                              sx={{
                                height: 20,
                                fontWeight: 700,
                                fontSize: '0.7rem',
                                bgcolor: row.balance_type === 'Dr' ? '#ccfbf1' : '#fef3c7',
                                color: row.balance_type === 'Dr' ? '#0f766e' : '#b45309',
                              }}
                            />
                          </TableCell>
                          <TableCell align="right">{row.age_0_30 ? fmtMoney(row.age_0_30) : '—'}</TableCell>
                          <TableCell align="right">{row.age_30_60 ? fmtMoney(row.age_30_60) : '—'}</TableCell>
                          <TableCell align="right">{row.age_60_90 ? fmtMoney(row.age_60_90) : '—'}</TableCell>
                          <TableCell align="right" sx={{ color: older90 > 0 ? '#e11d48' : 'inherit' }}>
                            {older90 ? fmtMoney(older90) : '—'}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>

              {/* Total Aggregate */}
              <Box sx={{ mt: 2.5, p: 2, bgcolor: '#f8fafc', borderRadius: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="body2" sx={{ fontWeight: 700, color: palette.ink }}>
                  Total Net Outstanding
                </Typography>
                <Typography
                  variant="h6"
                  sx={{
                    fontWeight: 800,
                    color: (selectedCustomer.net_balance ?? selectedCustomer.total_outstanding ?? 0) >= 0 ? '#0f766e' : '#c2410c',
                  }}
                >
                  {fmtMoney(Math.abs(selectedCustomer.net_balance ?? selectedCustomer.total_outstanding ?? 0))}{' '}
                  {(selectedCustomer.net_balance ?? selectedCustomer.total_outstanding ?? 0) >= 0 ? 'Dr' : 'Cr'}
                </Typography>
              </Box>
            </DialogContent>

            <DialogActions sx={{ p: 2 }}>
              <Button onClick={() => setSelectedCustomer(null)} sx={{ color: palette.ink }}>
                Close
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      {/* Tally Synchronization Dialog */}
      <Dialog
        open={syncModalOpen}
        onClose={() => !isSyncing && setSyncModalOpen(false)}
        maxWidth="sm"
        fullWidth
        PaperProps={{ sx: { borderRadius: 3 } }}
      >
        <DialogTitle sx={{ pb: 1, bgcolor: palette.ink, color: '#ffffff' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Stack direction="row" spacing={1.2} alignItems="center">
              <SyncRounded sx={{ color: '#2dd4bf' }} />
              <Typography variant="h6" sx={{ fontWeight: 700, color: '#ffffff' }}>
                Tally ERP Synchronization
              </Typography>
            </Stack>
            <IconButton onClick={() => setSyncModalOpen(false)} disabled={isSyncing} sx={{ color: '#ffffff' }}>
              <CloseRounded />
            </IconButton>
          </Stack>
        </DialogTitle>

        <DialogContent sx={{ p: 3 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
            Directly connect to Tally HTTP server to extract open company ledgers, bill allocations, and ageing breakdown into Surya ERP.
          </Typography>

          <Stack spacing={2.5}>
            {/* Tally URL */}
            <Box>
              <Typography variant="caption" sx={{ fontWeight: 600, color: palette.ink, mb: 0.5, display: 'block' }}>
                Tally Server URL (ODBC / HTTP Server)
              </Typography>
              <Stack direction="row" spacing={1}>
                <TextField
                  size="small"
                  value={tallyUrl}
                  onChange={(e) => setTallyUrl(e.target.value)}
                  placeholder="http://localhost:9000"
                  disabled={isSyncing}
                />
                <Button
                  variant="outlined"
                  onClick={handleTestTally}
                  disabled={isTesting || isSyncing}
                  sx={{ minWidth: 130, color: palette.teal, borderColor: palette.teal }}
                >
                  {isTesting ? <CircularProgress size={18} /> : 'Test Connection'}
                </Button>
              </Stack>
            </Box>

            {/* Test Result Feedback */}
            {testResult && (
              <Alert
                severity={testResult.success ? 'success' : 'error'}
                icon={testResult.success ? <CheckCircleOutlineRounded /> : <ErrorOutlineRounded />}
                sx={{ borderRadius: 2 }}
              >
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {testResult.message}
                </Typography>
                {testResult.companies?.length > 0 && (
                  <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                    Open Companies: {testResult.companies.join(', ')}
                  </Typography>
                )}
              </Alert>
            )}

            {/* Target Company */}
            <Box>
              <Typography variant="caption" sx={{ fontWeight: 600, color: palette.ink, mb: 0.5, display: 'block' }}>
                Company to Sync
              </Typography>
              <TextField
                select
                size="small"
                value={targetCompany}
                onChange={(e) => setTargetCompany(e.target.value)}
                disabled={isSyncing}
              >
                <MenuItem value="__ALL__">All Open Companies in Tally</MenuItem>
                {(testResult?.companies || dashboardData.companies || []).map((comp) => (
                  <MenuItem key={comp} value={comp}>
                    {comp}
                  </MenuItem>
                ))}
              </TextField>
            </Box>

            {/* Sync Progress Indicator */}
            {isSyncing && (
              <Box sx={{ p: 2, bgcolor: '#f0fdfa', borderRadius: 2, border: '1px solid #ccfbf1' }}>
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <CircularProgress size={22} sx={{ color: palette.teal }} />
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 700, color: palette.ink }}>
                      Synchronizing with Tally...
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Fetching customer ledgers and calculating ageing buckets across companies
                    </Typography>
                  </Box>
                </Stack>
              </Box>
            )}

            {/* Sync Result Feedback */}
            {syncResult && (
              <Alert
                severity={syncResult.success ? 'success' : 'error'}
                icon={syncResult.success ? <CheckCircleOutlineRounded /> : <ErrorOutlineRounded />}
                sx={{ borderRadius: 2 }}
              >
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {syncResult.message}
                </Typography>
                {syncResult.success && (
                  <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                    Synced across {syncResult.companies?.length || 0} companies: {syncResult.companies?.join(', ')}
                  </Typography>
                )}
              </Alert>
            )}

            {/* Instructions accordion */}
            <Box sx={{ border: `1px solid ${palette.line}`, borderRadius: 2, p: 1.5 }}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ cursor: 'pointer' }}
                onClick={() => setShowHelp(!showHelp)}
              >
                <Stack direction="row" spacing={1} alignItems="center">
                  <HelpOutlineRounded fontSize="small" sx={{ color: palette.teal }} />
                  <Typography variant="caption" sx={{ fontWeight: 700, color: palette.ink }}>
                    How to enable Tally ODBC / HTTP Server
                  </Typography>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {showHelp ? 'Hide' : 'Show'}
                </Typography>
              </Stack>

              <Collapse in={showHelp}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, lineHeight: 1.6 }}>
                  1. In Tally Prime or ERP 9, press <b>F12 &gt; Advanced Configuration</b>.<br />
                  2. Set <b>&quot;Tally is acting as&quot;</b> to <b>Both</b> or <b>Server</b>.<br />
                  3. Set <b>&quot;Enable ODBC Server&quot;</b> to <b>Yes</b> on port <b>9000</b>.<br />
                  4. Restart Tally and open your company/companies.<br />
                  5. Click <b>Test Connection</b> above, then click <b>Start Synchronization</b>!
                </Typography>
              </Collapse>
            </Box>
          </Stack>
        </DialogContent>

        <DialogActions sx={{ p: 2.5, bgcolor: '#fafafa', borderTop: `1px solid ${palette.line}` }}>
          <Button onClick={() => setSyncModalOpen(false)} disabled={isSyncing} sx={{ color: 'text.secondary' }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleRunSync}
            disabled={isSyncing}
            startIcon={isSyncing ? <CircularProgress size={18} color="inherit" /> : <SyncRounded />}
            sx={{
              bgcolor: palette.teal,
              fontWeight: 700,
              px: 3,
              '&:hover': { bgcolor: '#0d9488' },
            }}
          >
            {isSyncing ? 'Syncing...' : 'Start Synchronization'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
