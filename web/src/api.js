// Render passes the backend's bare hostname; locally the API runs on :8060.
const raw = import.meta.env.VITE_API_URL || "http://localhost:8060";
export const API = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;

export async function getJSON(path) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

export async function postJSON(path, body) {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return data;
}
