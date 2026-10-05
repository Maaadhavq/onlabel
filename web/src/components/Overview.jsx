import { modelName, nextWithStatus, statusOf } from "../review.js";
import { Check } from "./icons.jsx";

export function ClaimsOverview({ doc, sel, onSelect, hoverN, setHoverN, decisions }) {
  const tally = new Map();
  doc.claims.forEach((c) => {
    const s = statusOf(doc.reviews[c.n]);
    const key = `${s.tone}|${s.label}`;
    tally.set(key, (tally.get(key) || 0) + 1);
  });
  const decided = doc.claims.filter((c) => decisions[c.n]).length;
  return (
    <div className="card">
      <h3>Claims in reading order</h3>
      <div className="bar">
        {doc.claims.map((c) => {
          const s = statusOf(doc.reviews[c.n]);
          const d = decisions[c.n];
          return (
            <button
              key={c.n}
              type="button"
              className={`bar-seg tone-${s.tone}${hoverN === c.n ? " is-hover" : ""}`}
              aria-pressed={c.n === sel}
              aria-label={`Claim ${c.n}: ${s.label}${d ? `, reviewed (${d.choice === "agree" ? "agreed" : "changed"})` : ""}`}
              onClick={() => onSelect(c.n)}
              onMouseEnter={() => setHoverN(c.n)}
              onMouseLeave={() => setHoverN(null)}
            >
              {c.n}
              {d && <span className="decided" aria-hidden="true"><Check size={11} /></span>}
            </button>
          );
        })}
      </div>
      <div className="legend" aria-label="Jump to a claim by verdict">
        {[...tally.entries()].map(([key, n]) => {
          const [tone, label] = key.split("|");
          return (
            <button key={key} type="button" onClick={() => onSelect(nextWithStatus(doc, label, sel))} title={`Jump to the next claim that is ${label.toLowerCase()}`}>
              <span className={`swatch tone-${tone}`} />
              {n} {label.toLowerCase()}
            </button>
          );
        })}
      </div>
      {doc.status === "done" && doc.claims.length > 0 && (
        <p className="review-tally">
          {decided === 0 ? "No claims reviewed yet." : `You have reviewed ${decided} of ${doc.claims.length} claims.`}
        </p>
      )}
      <Progress doc={doc} />
    </div>
  );
}

function Progress({ doc }) {
  if (doc.status === "done") {
    if (doc.source === "sample" || !doc.stats) return null;
    return (
      <p className="small-note">
        Checked {doc.stats.n_claims} claims in {doc.stats.seconds} s using {doc.stats.tokens?.toLocaleString()} tokens.
      </p>
    );
  }
  if (doc.status === "error") return null;
  const done = Object.keys(doc.reviews).length;
  const latest = Object.values(doc.reviews).at(-1);
  const busy = latest?.trace?.find((t) => t.step === "judge")?.attempts?.filter((a) => a.skipped?.startsWith("per-minute")) || [];
  let text = "Finding the claims in your copy…";
  if (doc.status === "queued") text = `Waiting for ${doc.queuedAhead} review${doc.queuedAhead === 1 ? "" : "s"} ahead of yours…`;
  if (doc.status === "checking") text = `Checked ${done} of ${doc.claims.length} claims…`;
  return (
    <div className="status-line" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>
        {text}
        {busy.length > 0 && ` ${busy.map((a) => modelName(a.model).split(" on ")[0]).join(" and ")} at a per-minute limit, so ${modelName(latest.model).split(" on ")[0]} answered.`}
      </span>
    </div>
  );
}

export function RiskBox({ check }) {
  return (
    <div className={`boxwarn${check.ok ? " ok" : ""}`} role={check.ok ? undefined : "note"}>
      <p className="boxwarn-title">{check.title}</p>
      <p>{check.detail}</p>
      {!check.ok && check.evidence?.quote && (
        <blockquote>
          <span className="excerpt-cap" style={{ display: "block", marginBottom: 4 }}>
            {check.drug} · {check.evidence.section_path}
          </span>
          {check.evidence.quote}
        </blockquote>
      )}
    </div>
  );
}
