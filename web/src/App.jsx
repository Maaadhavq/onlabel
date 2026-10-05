import { useEffect, useState } from "react";
import { getJSON, postJSON } from "./api.js";

const SAMPLES = [
  { label: "wegovy", claim: "In clinical trials, adults taking Wegovy lost an average of 14.9% of their body weight at 68 weeks." },
  { label: "wegovy", claim: "Wegovy is approved for weight loss in children as young as 8." },
  { label: "ozempic", claim: "Ozempic has no serious side effects." },
  { label: "mounjaro", claim: "Mounjaro cures type 2 diabetes." },
];

const STATUS = {
  supported: { text: "Supported by the label", tone: "ok" },
  needs_qualifier: { text: "Needs a qualifier", tone: "warn" },
  unsupported: { text: "Not supported by the label", tone: "warn" },
  contradicted: { text: "Contradicted by the label", tone: "bad" },
  off_label: { text: "Off-label", tone: "bad" },
  needs_human_review: { text: "Needs human review", tone: "neutral" },
};

const FLAGS = {
  quote_not_found_in_excerpt: "The model quoted text that is not in the label excerpt. That quote was dropped.",
  cited_unknown_excerpt: "The model cited an excerpt it was not shown. That citation was dropped.",
  supported_without_grounded_quote: "The model said supported, but none of its quotes were found in the label.",
  supported_but_lists_violations: "The model said supported and also listed violations.",
  violation_without_grounded_quote: "The model flagged a violation without a quote that could be found in the label.",
  no_llm_available: "No language model was reachable, so the claim goes straight to a reviewer.",
};

function flagText(flag) {
  if (flag.startsWith("claim_figures_not_in_quotes:")) {
    return `The claim states ${flag.split(":")[1].replaceAll(",", ", ")}, but no quoted label text contains that figure.`;
  }
  return FLAGS[flag] || flag;
}

function useHealth() {
  const [health, setHealth] = useState({ status: "checking" });
  useEffect(() => {
    let stop = false;
    let tries = 0;
    async function poll() {
      try {
        const h = await getJSON("/health");
        if (stop) return;
        setHealth(h);
        if (h.status === "loading") setTimeout(poll, 3000);
      } catch {
        if (stop) return;
        tries += 1;
        setHealth({ status: tries > 24 ? "down" : "waking" });
        if (tries <= 24) setTimeout(poll, 5000);
      }
    }
    poll();
    return () => { stop = true; };
  }, []);
  return health;
}

export default function App() {
  const health = useHealth();
  const [labels, setLabels] = useState([]);
  const [label, setLabel] = useState("");
  const [claim, setClaim] = useState(SAMPLES[0].claim);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (health.status === "ready") getJSON("/labels").then(setLabels).catch(() => {});
  }, [health.status]);

  async function check(e) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await postJSON("/reviews", { claim, labels: label ? [label] : null }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const ready = health.status === "ready";
  return (
    <main>
      <header>
        <h1>OnLabel</h1>
        <p className="lede">
          Checks a promotional drug claim against the FDA label and shows the label text behind the verdict.
          It prepares evidence for an MLR reviewer. It does not approve content.
        </p>
      </header>

      <ServerState health={health} />

      <form onSubmit={check}>
        <label htmlFor="claim">Claim</label>
        <textarea id="claim" rows={3} maxLength={600} value={claim} onChange={(e) => setClaim(e.target.value)} />
        <div className="row">
          <label htmlFor="label">Label</label>
          <select id="label" value={label} onChange={(e) => setLabel(e.target.value)}>
            <option value="">Any indexed label</option>
            {labels.map((l) => (
              <option key={l.key} value={l.key}>{l.drug} (v{l.version})</option>
            ))}
          </select>
          <button type="submit" disabled={!ready || busy || claim.trim().length < 8}>
            {busy ? "Checking…" : "Check claim"}
          </button>
        </div>
        <div className="samples">
          <span>Try:</span>
          {SAMPLES.map((s) => (
            <button type="button" key={s.claim} className="link" onClick={() => { setClaim(s.claim); setLabel(s.label); }}>
              {s.claim.length > 48 ? `${s.claim.slice(0, 48)}…` : s.claim}
            </button>
          ))}
        </div>
      </form>

      {error && <p className="error" role="alert">{error}</p>}
      {result && <Result r={result} />}
    </main>
  );
}

function ServerState({ health }) {
  if (health.status === "ready") return null;
  const text = {
    checking: "Connecting to the API…",
    waking: "Waking the free-tier server. This can take up to a minute.",
    loading: "Loading the label index and models…",
    error: `The API could not start: ${health.error}`,
    down: "The API is not answering. Try again in a few minutes.",
  }[health.status];
  return <p className="notice">{text}</p>;
}

function Result({ r }) {
  const s = STATUS[r.status] || { text: r.status, tone: "neutral" };
  return (
    <section className="result" aria-live="polite">
      <div className="verdict">
        <span className={`pill ${s.tone}`}>{s.text}</span>
        {r.model_verdict && r.model_verdict !== r.status && (
          <span className="muted">model said: {r.model_verdict.replaceAll("_", " ")}</span>
        )}
      </div>
      {r.violations?.length > 0 && (
        <ul className="chips">
          {r.violations.map((v) => <li key={v}>{v.replaceAll("_", " ")}</li>)}
        </ul>
      )}
      <p>{r.reasoning}</p>

      {r.flags?.length > 0 && (
        <div className="flags">
          <h3>What the checks caught</h3>
          <ul>{[...new Set(r.flags)].map((f) => <li key={f}>{flagText(f)}</li>)}</ul>
        </div>
      )}

      <h3>Label evidence</h3>
      {r.evidence.length === 0 ? (
        <p className="muted">No quote survived the grounding check.</p>
      ) : (
        r.evidence.map((e, i) => (
          <figure key={i} className="evidence">
            <blockquote>{e.quote}</blockquote>
            <figcaption>
              {e.section_path} · {e.match} match · <a href={e.url} target="_blank" rel="noreferrer">DailyMed</a>
            </figcaption>
          </figure>
        ))
      )}

      <details>
        <summary>Trace: {r.model || "no model"} ({r.source}), {r.tokens} tokens, {r.latency_s}s</summary>
        <ol className="trace">
          {r.trace.map((t, i) => (
            <li key={i}><code>{t.step}</code> {JSON.stringify(Object.fromEntries(Object.entries(t).filter(([k]) => k !== "step")))}</li>
          ))}
        </ol>
        <h4>Retrieved excerpts</h4>
        <ol className="trace">
          {r.retrieved.map((h) => (
            <li key={h.chunk_id}>
              <code>{h.chunk_id}</code> {h.section} (dense #{h.dense_rank ?? "–"}, BM25 #{h.bm25_rank ?? "–"})
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
