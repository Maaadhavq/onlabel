import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { followReview, getJSON, postJSON } from "./api.js";
import { applyEvent, buildAudit, emptyDoc, replay } from "./review.js";
import Topbar from "./components/Topbar.jsx";
import { EditorCard, ProofCard } from "./components/CopyPanel.jsx";
import { ClaimsOverview, RiskBox } from "./components/Overview.jsx";
import Inspector, { TABS } from "./components/Inspector.jsx";

// Reviews stored with the page: they open while the free server sleeps or quotas run out.
const SAMPLE_ORDER = ["wegovy-spring-email", "ozempic-web-banner", "mounjaro-hcp-detail-aid"];
const SAMPLES = Object.values(import.meta.glob("./samples/*.json", { eager: true, import: "default" }))
  .map((s) => ({ ...s, nClaims: s.events.find((e) => e.event === "claims")?.data.claims.length ?? 0 }))
  .sort((a, b) => SAMPLE_ORDER.indexOf(a.id) - SAMPLE_ORDER.indexOf(b.id));

// A reviewer's decisions live in this browser only, per review.
const decisionKey = (id) => `onlabel:decisions:${id}`;
function loadDecisions(id) {
  try {
    return JSON.parse(localStorage.getItem(decisionKey(id)) || "{}");
  } catch {
    return {};
  }
}
function saveDecisions(id, value) {
  try {
    localStorage.setItem(decisionKey(id), JSON.stringify(value));
  } catch {
    /* storage blocked (private window): decisions stay in memory */
  }
}

function useHealth() {
  const [health, setHealth] = useState({ status: "checking" });
  useEffect(() => {
    let stop = false;
    let tries = 0;
    const poll = async () => {
      try {
        const h = await getJSON("/health");
        if (stop) return;
        setHealth(h);
        if (h.status === "loading") setTimeout(poll, 2000);
      } catch {
        if (stop) return;
        tries += 1;
        setHealth({ status: tries > 30 ? "down" : "waking", waitedS: tries * 4 });
        if (tries <= 30) setTimeout(poll, 4000);
      }
    };
    poll();
    return () => { stop = true; };
  }, []);
  return health;
}

function ServerNotice({ health }) {
  if (health.status === "ready") return null;
  if (health.status === "error") return <div className="error-box" role="alert">The server could not start: {health.error}</div>;
  if (health.status === "down") return <div className="error-box" role="alert">The server is not answering. The samples still open; try a live check later.</div>;
  return (
    <div className="notice" role="status">
      <h2>Starting the review server</h2>
      <p>Free hosting puts the server to sleep after 15 minutes without visitors. Starting it again takes about 30 seconds.</p>
      <div className="progress" aria-hidden="true"><div /></div>
      <p className="mono-note">{health.status === "loading" ? "Loading the label index" : `Waiting for /health${health.waitedS ? `, ${health.waitedS} s so far` : ""}`}</p>
    </div>
  );
}

const firstFlagged = (doc) => {
  const flagged = doc.claims.find((c) => doc.reviews[c.n] && doc.reviews[c.n].status !== "supported");
  return flagged ? flagged.n : 1;
};

export default function App() {
  const health = useHealth();
  const ready = health.status === "ready";
  const [apiLabels, setApiLabels] = useState([]);
  const [draft, setDraft] = useState({ text: "", label: "", audience: "consumer" });
  const [doc, setDoc] = useState(null);
  const [editing, setEditing] = useState(true);
  const [sel, setSel] = useState(1);
  const [tab, setTab] = useState("evidence");
  const [rewrites, setRewrites] = useState({});
  const [decisions, setDecisions] = useState({});
  const [hoverN, setHoverN] = useState(null);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const stopStream = useRef(null);

  useEffect(() => {
    if (ready) getJSON("/labels").then(setApiLabels).catch(() => {});
  }, [ready]);
  useEffect(() => () => stopStream.current?.(), []);

  // Labels for the picker: the API's list, or the ones the samples carry while it sleeps.
  const labels = useMemo(() => {
    if (apiLabels.length) return apiLabels;
    const seen = new Map();
    SAMPLES.forEach((s) => s.events.find((e) => e.event === "start")?.data.labels.forEach((l) => {
      seen.set(l.key, { key: l.key, drug: (l.products || [l.key])[0], version: l.version, set_id: l.set_id });
    }));
    return [...seen.values()].sort((a, b) => a.drug.localeCompare(b.drug));
  }, [apiLabels]);

  const reviewing = !editing && doc;

  // Reviewer keys: J/K or arrows move between claims, 1-3 switch tabs. Never while typing.
  useEffect(() => {
    if (!reviewing || !doc.claims.length) return undefined;
    const total = doc.claims.length;
    const onKey = (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.target.closest?.("input, textarea, select, [contenteditable], [role=menu]")) return;
      if (e.key === "j" || e.key === "J" || e.key === "ArrowRight") {
        setSel((s) => (s >= total ? 1 : s + 1));
        e.preventDefault();
      } else if (e.key === "k" || e.key === "K" || e.key === "ArrowLeft") {
        setSel((s) => (s <= 1 ? total : s - 1));
        e.preventDefault();
      } else if (["1", "2", "3"].includes(e.key)) {
        setTab(TABS[Number(e.key) - 1][0]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reviewing, doc?.claims.length]);

  const select = useCallback((n) => setSel(n), []);

  const openDoc = (next, rewritesFor) => {
    setDoc(next);
    setRewrites(rewritesFor);
    setDecisions(loadDecisions(next.id));
    setTab("evidence");
    setEditing(false);
    setSubmitError("");
  };

  const openSample = (sample) => {
    stopStream.current?.();
    const next = replay({ source: "sample", id: sample.id, title: sample.title, note: sample.note, text: sample.text, audience: sample.audience }, sample.events);
    setDraft({ text: sample.text, label: sample.label, audience: sample.audience });
    // Stored rewrites wait behind the button, as a live one would.
    openDoc(next, Object.fromEntries(Object.entries(sample.rewrites || {}).map(([n, data]) => [n, { state: "stored", data }])));
    setSel(firstFlagged(next));
  };

  const newCheck = () => {
    stopStream.current?.();
    setDoc(null);
    setEditing(true);
    setDraft((d) => ({ text: "", label: "", audience: d.audience }));
    setSubmitError("");
    window.scrollTo({ top: 0 });
  };

  const check = async () => {
    setSubmitError("");
    setSubmitting(true);
    try {
      const { id } = await postJSON("/documents", { text: draft.text, label: draft.label || null, audience: draft.audience });
      stopStream.current?.();
      openDoc(emptyDoc({ source: "live", id, title: "Your copy", note: "", text: draft.text, audience: draft.audience }), {});
      setSel(1);
      stopStream.current = followReview(id, (event, data) => setDoc((d) => (d && d.id === id ? applyEvent(d, event, data) : d)));
    } catch (err) {
      setSubmitError(err.message);
      setEditing(true);
    } finally {
      setSubmitting(false);
    }
  };

  const rewrite = async () => {
    if (!doc) return;
    const n = sel;
    if (doc.source === "sample") {
      setRewrites((r) => (r[n]?.state === "stored" ? { ...r, [n]: { ...r[n], state: "done" } } : r));
      return;
    }
    setRewrites((r) => ({ ...r, [n]: { state: "loading" } }));
    try {
      const data = await postJSON(`/documents/${doc.id}/claims/${n}/rewrite`);
      setRewrites((r) => ({ ...r, [n]: { state: "done", data } }));
    } catch (err) {
      setRewrites((r) => ({ ...r, [n]: { state: "error", error: err.message } }));
    }
  };

  const decide = (n, value) => {
    setDecisions((prev) => {
      const next = { ...prev };
      if (value) next[n] = { ...value, at: new Date().toISOString() };
      else delete next[n];
      saveDecisions(doc.id, next);
      return next;
    });
  };

  const download = () => {
    const shown = Object.fromEntries(Object.entries(rewrites).filter(([, r]) => r.state === "done"));
    const blob = new Blob([JSON.stringify(buildAudit(doc, decisions, shown), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `onlabel-review-${doc.id}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const liveBusy = doc?.source === "live" && !["done", "error"].includes(doc.status);
  const canCheck = ready && !submitting && !liveBusy && draft.text.trim().length >= 20;

  return (
    <>
      <Topbar samples={SAMPLES} onOpenSample={openSample} onNew={newCheck} />
      <main className="workspace">
        <section className="col-copy" aria-label="Copy under review">
          <ServerNotice health={health} />
          {reviewing ? (
            <>
              <ProofCard doc={doc} sel={sel} onSelect={select} onEdit={() => setEditing(true)} onDownload={download} hoverN={hoverN} setHoverN={setHoverN} />
              {doc.status === "error" && <div className="error-box" role="alert">{doc.error}</div>}
              {doc.claims.length > 0 && (
                <ClaimsOverview doc={doc} sel={sel} onSelect={select} hoverN={hoverN} setHoverN={setHoverN} decisions={decisions} />
              )}
              {doc.checks.map((c) => <RiskBox key={c.label} check={c} />)}
            </>
          ) : (
            <EditorCard
              labels={labels}
              draft={draft}
              setDraft={setDraft}
              onCheck={check}
              canCheck={canCheck}
              busy={submitting || liveBusy}
              samples={SAMPLES}
              onOpenSample={openSample}
              error={submitError}
              ready={ready}
            />
          )}
        </section>
        <section className="col-inspector" id="claim-panel" aria-label="Claim details">
          <Inspector
            doc={reviewing ? doc : null}
            sel={sel}
            onSelect={select}
            tab={tab}
            setTab={setTab}
            rewrite={rewrites[sel]}
            onRewrite={rewrite}
            canRewrite={doc?.source === "sample" ? rewrites[sel]?.state === "stored" : ready && rewrites[sel]?.state !== "loading"}
            rewriteUnavailable={doc?.source === "sample" && !rewrites[sel] ? "This sample has no stored wording for this claim. Check the copy live to get one." : ""}
            decision={decisions[sel]}
            onDecide={decide}
          />
        </section>
      </main>
    </>
  );
}
