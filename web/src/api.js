// Render passes the backend's bare hostname; locally the API runs on :8060.
const raw = import.meta.env.VITE_API_URL || "http://localhost:8060";
export const API = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;

async function asJSON(r) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
    const err = new Error(detail || `The server answered ${r.status}.`);
    err.status = r.status;
    throw err;
  }
  return data;
}

export const getJSON = (path) => fetch(`${API}${path}`).then(asJSON);

export const postJSON = (path, body) =>
  fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(asJSON);

const EVENTS = ["queued", "start", "claims", "claim", "document", "done", "error"];

// Stream a document review. EventSource reconnects on its own and sends Last-Event-ID, so a
// dropped connection resumes; if streaming keeps failing, poll the snapshot instead.
export function followReview(id, onEvent) {
  let closed = false;
  let seen = -1;
  let source = null;
  let poll = null;
  let failures = 0;

  const deliver = (ev) => {
    if (ev.id <= seen || closed) return;
    seen = ev.id;
    onEvent(ev.event, ev.data);
    if (ev.event === "done" || ev.event === "error") stop();
  };

  const startPolling = () => {
    if (poll || closed) return;
    poll = setInterval(async () => {
      try {
        const snap = await getJSON(`/documents/${id}`);
        snap.events.forEach(deliver);
      } catch {
        /* keep trying until done or stopped */
      }
    }, 2000);
  };

  function stop() {
    closed = true;
    source?.close();
    if (poll) clearInterval(poll);
  }

  if (typeof EventSource === "undefined") {
    startPolling();
  } else {
    source = new EventSource(`${API}/documents/${id}/events`);
    EVENTS.forEach((name) =>
      source.addEventListener(name, (e) => deliver({ id: Number(e.lastEventId), event: name, data: JSON.parse(e.data) })),
    );
    source.onerror = () => {
      failures += 1;
      if (failures >= 3) {
        source.close();
        startPolling();
      }
    };
  }
  return stop;
}
