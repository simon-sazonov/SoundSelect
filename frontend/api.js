// The back end's API (docs/api.md). Every call answers JSON or throws an Error whose message
// can be shown as it is.

const BASE = "/api/v1";

async function problem(res) {
  try {
    const body = await res.json();
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
    if (body.detail?.message) return body.detail.message;
  } catch { /* not JSON */ }
  return `The app answered ${res.status}.`;
}

export async function call(path, { method = "GET", json, form } = {}) {
  const init = { method, headers: {} };
  if (json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(json); }
  if (form) init.body = form;
  let res;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new Error("Can't reach SoundSelect. Is the app running on your computer?");
  }
  if (!res.ok) {
    const err = new Error(await problem(res));
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

export async function text(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(await problem(res));
  return res.text();
}

export const url = (path, params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  const s = q.toString();
  return BASE + path + (s ? `?${s}` : "");
};

// what rarely changes is asked for once per visit
const once = {};
export const health = () => (once.health ??= call("/health").catch((e) => { delete once.health; throw e; }));
export const instruments = () => (once.instruments ??= call("/instruments"));
export function settings(fresh = false) {
  if (fresh) delete once.settings;
  return (once.settings ??= call("/settings").catch((e) => { delete once.settings; throw e; }));
}
export async function saveSettings(patch) {
  const current = await settings();
  const saved = await call("/settings", { method: "PUT", json: { ...current, ...patch } });
  once.settings = Promise.resolve(saved);
  return saved;
}
