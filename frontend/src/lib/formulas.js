/**
 * Costing formulas. Mirrors backend clssurya/utils/costing.py - the server is authoritative,
 * these only drive live previews. Full precision is kept; round only when displaying.
 *
 * Base = carried + added (+ tooling in Stage 3); Rejection = Base x rejection%; Total = Base + Rejection; Unit = Total / qty
 */

/** @param {*} v @returns {number} */
export const n = (v) => Number(v) || 0;

/** The single money-rounding rule: 2 dp, half up (display only). @param {*} v */
export const money = (v) => Math.round((n(v) + Number.EPSILON) * 100) / 100;

const r9 = (v) => Math.round(v * 1e9) / 1e9;

/**
 * @param {number} carried @param {number} added @param {number} rejectionPercent @param {number} qty @param {number} [tooling]
 * @returns {{base:number, rejectionAmount:number, batchTotal:number, unitCost:number}}
 */
export function stageTotals(carried, added, rejectionPercent, qty, tooling = 0) {
  const base = n(carried) + n(added) + n(tooling); // rejection is charged on everything, tooling included
  const rejectionAmount = (base * n(rejectionPercent)) / 100;
  const batchTotal = base + rejectionAmount;
  return { base, rejectionAmount, batchTotal, unitCost: n(qty) ? batchTotal / n(qty) : 0 };
}

/** Tooling cost = tooling % x (carried cost + the charges marked "in tooling base"). */
export const toolingAmount = (carried, markedCharges, percent) => ((n(carried) + n(markedCharges)) * n(percent)) / 100;

/** Wastage = material used - (output qty x weight per piece). */
export const stage1Wastage = (used, qty, weightPerPiece) => r9(n(used) - n(qty) * n(weightPerPiece));

/**
 * @param {number} amount @param {number} gstPercent @param {string} vendorState @param {string} companyState
 * @returns {{cgst:number, sgst:number, igst:number}}
 */
export function splitGst(amount, gstPercent, vendorState, companyState) {
  const tax = (n(amount) * n(gstPercent)) / 100;
  const same = String(vendorState || '').trim().toLowerCase() === String(companyState || '').trim().toLowerCase();
  return same ? { cgst: tax / 2, sgst: tax / 2, igst: 0 } : { cgst: 0, sgst: 0, igst: tax };
}

/** Landed cost: spread extra charges over rows by value. @param {number[]} amounts @param {number} extra */
export function allocateExtra(amounts, extra) {
  const total = amounts.reduce((a, b) => a + b, 0);
  return amounts.map((a) => (total ? (n(extra) * a) / total : 0));
}

/**
 * Live preview for a Stage 1/2/3 batch form.
 * Row "extra_cost" is entered PER PIECE and multiplied by the quantity (counted once, as an added cost).
 * Stage 3 order: carried + charges, then tooling % of (carried + marked charges), then rejection on the lot.
 * @param {1|2|3} stage @param {object} v form values
 * @returns {{top:object, rows:object}} patch for the form
 */
export function stageCalc(stage, v) {
  const qty = n(v.quantity);

  let carried = 0;
  let added = 0;
  let extraCostTotal = 0;
  let used = 0;

  const items = (v.items || []).map((r) => {
    const price = n(r.unit_price);
    const total = n(r.per_unit_utilization) * qty;
    const actualAmount = n(r.actual_utilization) * price;
    const rowExtra = n(r.extra_cost) * qty;

    const out = {
      total_utilization: total,
      amount: total * price,
      per_unit_amount: n(r.per_unit_utilization) * price,
      actual_amount: actualAmount,
    };

    if (r.is_carried_in) {
      carried += actualAmount;
    } else {
      added += actualAmount;
    }

    extraCostTotal += rowExtra;
    used += n(r.actual_utilization);

    return out;
  });

  added += extraCostTotal;

  const rows = { items };

  let marked = 0;
  let tooling = 0;

  if (stage === 3) {
    rows.charges = (v.charges || []).map((c) => {
      const amount = n(c.per_unit_price) * qty;
      added += amount;

      if (Number(c.in_tooling_base)) marked += amount;

      return { amount };
    });

    tooling = toolingAmount(carried, marked, v.tooling_percent);
  }

  // Unit cost without extra cost: used for the next stage.
  const baseTotals = stageTotals(
    carried,
    added,
    v.rejection_percent,
    qty,
    tooling
  );

  // Current-stage cost including extra cost.
  const currentTotals = stageTotals(
    carried,
    added + extraCostTotal,
    v.rejection_percent,
    qty,
    tooling
  );

  const top = {
    carried_cost: carried,
    added_cost: added + extraCostTotal,
    extra_cost_total: extraCostTotal,
    rejection_amount: currentTotals.rejectionAmount,
    batch_total: currentTotals.batchTotal,
    unit_cost: currentTotals.unitCost,
    unit_cost_without_extra: baseTotals.unitCost,
  };

  if (stage === 3) {
    top.tooling_base = carried + marked;
    top.tooling_amount = tooling;
  }

  if (stage === 1) {
    top.wastage_qty = stage1Wastage(used, qty, v.weight_per_piece);
  }

  return { top, rows };
}

/** Live preview for Purchase Entry. @param {object} v @param {{masters:object, companyState:string}} ctx */
export function purchaseCalc(v, { masters, companyState }) {
  const vendorState = masters.Vendor?.[v.vendor]?.state || '';
  let taxable = 0;
  let tax = 0;
  let rowExtra = 0;
  const items = (v.items || []).map((r) => {
    const amount = n(r.quantity) * n(r.rate);
    rowExtra += n(r.extra_charge);
    const g = splitGst(amount, r.gst_percent, vendorState, companyState);
    taxable += amount;
    tax += g.cgst + g.sgst + g.igst;
    return { amount, ...g, uom: masters.Product?.[r.product]?.uom || '' };
  });
  const shares = allocateExtra(items.map((i) => i.amount), v.extra_charges);
  items.forEach((it, i) => {
    const q = n(v.items[i].quantity);
    // landed = amount + this row's extra charge + its share of the bill-level extra charges
    it.landed_rate = q ? (it.amount + n(v.items[i].extra_charge) + shares[i]) / q : 0;
  });
  return {
    top: { vendor_state: vendorState, taxable_amount: taxable, tax_amount: tax, grand_total: taxable + tax + n(v.extra_charges) + rowExtra },
    rows: { items },
  };
}


export function quotationTaxCalc(v) {
  const items = v.items || [];

  const subtotal = items.reduce(
    (total, item) =>
      total + n(item.quantity) * n(item.rate),
    0
  );

  const discountPercent = Math.min(
    100,
    Math.max(0, n(v.discount_percent))
  );

  const discountAmount = subtotal * discountPercent / 100;
  const taxableAmount = Math.max(0, subtotal - discountAmount);

  const gstPercent = Math.max(0, n(v.gst_percent));
  const totalGST = taxableAmount * gstPercent / 100;

  const isIGST = v.gst_type === 'IGST';

  const cgstAmount = isIGST ? 0 : totalGST / 2;
  const sgstAmount = isIGST ? 0 : totalGST / 2;
  const igstAmount = isIGST ? totalGST : 0;

  return {
    subtotal,
    discount_amount: discountAmount,
    taxable_amount: taxableAmount,
    cgst_amount: cgstAmount,
    sgst_amount: sgstAmount,
    igst_amount: igstAmount,
    total_amount: subtotal,
    grand_total: taxableAmount + totalGST,
  };
}



/** Quotation / Sales Order preview. Below cost = rate < Finished unit cost. */
export function salesCalc(v, { masters, finishedCost }) {
  let total = 0;
  let below = 0;
  const items = (v.items || []).map((r) => {
    const cost = n(finishedCost?.[r.product]?.unit_price);
    const amount = n(r.quantity) * n(r.rate);
    const isBelow = n(r.rate) < cost && !!r.product ? 1 : 0;
    total += amount;
    below = below || isBelow;
    return { amount, uom: masters.Product?.[r.product]?.uom || '', production_cost: cost, below_cost: isBelow, pending_qty: n(r.quantity) - n(r.dispatched_qty) };
  });
  return { top: { total_amount: total, below_cost: below }, rows: { items } };
}