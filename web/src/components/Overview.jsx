import { modelName, statusOf } from "../review.js";

export function ClaimsOverview({ doc, sel, onSelect }) {
  const tally = new Map();
  doc.claims.forEach((c) => {
    const s = statusOf(doc.reviews[c.n]);
    const key = `${s.tone}|${s.label}`;
    tally.set(key, (tally.get(key) || 0) + 1);
  });
  return (
    <div className="card">
      <h3>Claims in reading order</h3>
      <div className="bar">
        {doc.claims.map((c) => {
          const s = statusOf(doc.reviews[c.n]);
          return (
            <button
              key={c.n}
              type="button"
              className={`bar-seg tone-${s.tone}`}
              aria-pressed={c.n === sel}
              aria-label={`Claim ${c.n}: ${s.label}`}
              onClick={() => onSelect(c.n)}
            >
              {c.n}
            </button>
          );
        })}
      </div>
      <div className="legend">
        {[...tally.entries()].map(([key, n]) => {
          const [tone, label] = key.split("|");
          return (
            <span key={key}>
              <span className={`swatch tone-${tone}`} />
              {n} {label.toLowerCase()}
            </span>
          );
        })}
      </div>
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
