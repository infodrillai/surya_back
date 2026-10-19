import { Box, Tab, Tabs, Typography } from '@mui/material';
import { useState } from 'react';
import CrudPage from '../components/CrudPage';
import { STAGE_CONFIGS } from '../config/resources';

const LABELS = ['Stage 1 · Raw to semi', 'Stage 2 · Semi to semi', 'Stage 3 · Charges to finished'];

/** Three independent screens that link only through stock. */
export default function BatchPage() {
  const [tab, setTab] = useState(0);
  return (
    <Box>
      <Typography variant="h5">Production batches</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Each stage consumes the stock the previous stage produced.</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2.5, borderBottom: 1, borderColor: 'divider' }}>
        {LABELS.map((l) => <Tab key={l} label={l} />)}
      </Tabs>
      <CrudPage key={tab} config={STAGE_CONFIGS[tab]} embedded />
    </Box>
  );
}
