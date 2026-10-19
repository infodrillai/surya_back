/**
 * Thin fetch wrapper for Frappe: session cookie, CSRF header, 401 handling, readable errors.
 * @typedef {{method?: 'GET'|'POST'|'PUT'|'DELETE', body?: object, params?: Record<string,string>}} ReqOptions
 */
let csrfToken = null;
let onUnauthorized = () => {};

export const setCsrf = (t) => (csrfToken = t);
export const setUnauthorizedHandler = (fn) => (onUnauthorized = fn);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const strip = (html) => String(html).replace(/<[^>]*>/g, '').trim();

function readError(data, status) {
  try {
    if (data?._server_messages) {
      const msgs = JSON.parse(data._server_messages).map((m) => strip(JSON.parse(m).message));
      if (msgs.length) return msgs.join('\n');
    }
  } catch { /* fall through */ }
  if (data?.exception) return strip(String(data.exception).split(': ').slice(1).join(': ') || data.exception);
  return data?.message && typeof data.message === 'string' ? data.message : `Request failed (${status})`;
}

/** @param {string} path @param {ReqOptions} [opt] */
export async function request(path, { method = 'GET', body, params } = {}) {
  const url = params ? `${path}?${new URLSearchParams(params)}` : path;
  const res = await fetch(url, {
    method,
    credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw new ApiError(readError(data, res.status), res.status);
  return data;
}

/** Call a whitelisted method. Reads use GET (no CSRF needed), writes POST. */
export const call = async (method, args = {}, { get = false } = {}) => {
  if (get) {
    const params = Object.fromEntries(Object.entries(args).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]));
    return (await request(`/api/method/${method}`, { params })).message;
  }
  return (await request(`/api/method/${method}`, { method: 'POST', body: args })).message;
};

const res = (dt) => `/api/resource/${encodeURIComponent(dt)}`;

/** @param {string} doctype */
export const getList = async (doctype, { fields = ['*'], orderBy = 'modified desc' } = {}) =>
  (await request(res(doctype), { params: { fields: JSON.stringify(fields), limit_page_length: '0', order_by: orderBy } })).data;
export const getDoc = async (doctype, name) => (await request(`${res(doctype)}/${encodeURIComponent(name)}`)).data;
export const insertDoc = async (doctype, doc) => (await request(res(doctype), { method: 'POST', body: doc })).data;
export const updateDoc = async (doctype, name, doc) => (await request(`${res(doctype)}/${encodeURIComponent(name)}`, { method: 'PUT', body: doc })).data;
export const deleteDoc = (doctype, name) => request(`${res(doctype)}/${encodeURIComponent(name)}`, { method: 'DELETE' });

/** complete | reopen | approve | revise | make_sales_order */
export const runAction = (doctype, name, action) => call('clssurya.api.run_action', { doctype, name, action });

export async function login(usr, pwd) {
  await request('/api/method/login', { method: 'POST', body: { usr, pwd } });
}
export const logoutRequest = () => request('/api/method/logout', { method: 'POST' }).catch(() => {});
