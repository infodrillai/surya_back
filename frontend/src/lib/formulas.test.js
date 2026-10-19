import { describe, expect, it } from 'vitest';
import { allocateExtra, splitGst, stage1Wastage, stageCalc, stageTotals } from './formulas';

describe('costing examples from the plan', () => {
  it('Stage 1: 10 kg @ 250, 5% rejection, 99 pcs x 0.1 kg', () => {
    const r = stageCalc(1, {
      quantity: 99, weight_per_piece: 0.1, rejection_percent: 5,
      items: [{ per_unit_utilization: 10 / 99, unit_price: 250, actual_utilization: 10 }],
    });
    expect(r.top.added_cost).toBeCloseTo(2500, 6);
    expect(r.top.rejection_amount).toBeCloseTo(125, 6);
    expect(r.top.batch_total).toBeCloseTo(2625, 6);
    expect(r.top.unit_cost).toBeCloseTo(26.5152, 4);
    expect(r.top.wastage_qty).toBeCloseTo(0.1, 6);
  });

  it('Stage 2: 100 pcs @ 26.5152 carried + 400 raw, 5% rejection', () => {
    const r = stageCalc(2, {
      quantity: 100, rejection_percent: 5,
      items: [
        { is_carried_in: 1, per_unit_utilization: 1, unit_price: 26.5152, actual_utilization: 100 },
        { per_unit_utilization: 0.04, unit_price: 100, actual_utilization: 4 },
      ],
    });
    expect(r.top.carried_cost).toBeCloseTo(2651.52, 2);
    expect(r.top.added_cost).toBeCloseTo(400, 6);
    expect(r.top.rejection_amount).toBeCloseTo(152.576, 3);
    expect(r.top.batch_total).toBeCloseTo(3204.096, 3);
    expect(r.top.unit_cost).toBeCloseTo(32.04096, 5);
  });

  it('Stage 3 adds charges per unit x qty', () => {
    const r = stageCalc(3, {
      quantity: 10, rejection_percent: 0,
      items: [{ is_carried_in: 1, per_unit_utilization: 1, unit_price: 32, actual_utilization: 10 }],
      charges: [{ per_unit_price: 3 }, { per_unit_price: 2 }],
    });
    expect(r.top.batch_total).toBeCloseTo(370, 6);
    expect(r.top.unit_cost).toBeCloseTo(37, 6);
  });
});

describe('helpers', () => {
  it('GST splits by state', () => {
    expect(splitGst(1000, 18, 'Gujarat', 'gujarat')).toEqual({ cgst: 90, sgst: 90, igst: 0 });
    expect(splitGst(1000, 18, 'Kerala', 'Gujarat')).toEqual({ cgst: 0, sgst: 0, igst: 180 });
  });
  it('allocates extra charges by value', () => expect(allocateExtra([100, 300], 40)).toEqual([10, 30]));
  it('zero quantity gives zero unit cost', () => expect(stageTotals(0, 100, 5, 0).unitCost).toBe(0));
  it('wastage is rounded to 9 dp', () => expect(stage1Wastage(10, 99, 0.1)).toBe(0.1));
});
