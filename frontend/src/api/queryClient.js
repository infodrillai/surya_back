import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } },
});

/** Which server queries must refresh when a master changes. */
export const DEPENDENT_QUERIES = {
  Product: [['stage_rows'], ['finished_cost'], ['list', 'Inventory']],
  BOM: [['stage_rows']],
  Customer: [], Vendor: [], UOM: [], Category: [], Process: [], Charge: [], Company: [],
};
