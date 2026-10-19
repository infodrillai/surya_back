const nf = (dp) => new Intl.NumberFormat('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: dp });

/** Display-only rounding. @param {*} v @param {number} [dp] */
export const fmtNum = (v, dp = 2) => (v === '' || v == null || Number.isNaN(Number(v)) ? '' : nf(dp).format(Number(v)));
export const fmtMoney = (v, dp = 2) => (v === '' || v == null ? '' : `₹${fmtNum(v, dp)}`);
export const fmtDate = (v) => (v ? new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '');
export const todayISO = () => new Date().toISOString().slice(0, 10);
