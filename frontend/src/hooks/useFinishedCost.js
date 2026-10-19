import { useQuery } from '@tanstack/react-query';
import { call } from '../api/client';

/** { productCode: {stock, unit_price} } for Finished stock. Sales can read this, not the ledger. */
export const useFinishedCost = (enabled = true) =>
  useQuery({ queryKey: ['finished_cost'], queryFn: () => call('clssurya.api.get_finished_cost', {}, { get: true }), enabled });
