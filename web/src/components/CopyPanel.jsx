import { useEffect, useRef } from "react";
import { formatDate, segments, statusOf } from "../review.js";

const MAX_CHARS = 4000;

export function EditorCard({ draft, setDraft, onCheck, canCheck, samples, onOpenSample, error, ready }) {
  return (
    <div className="sheet start">
      <h2>Paste the copy you want checked</h2>
      <div className="editor">
        <label className="field-label" htmlFor="copy-in">Promotional copy</label>
        <textarea
          id="copy-in"
          value={draft.text}
          maxLength={MAX_CHARS}
          placeholder="An email, web page, banner or detail aid. Up to 4,000 characters."
          onChange={(e) => setDraft({ ...draft, text: e.target.value })}
        />
        <div className="editor-foot">
          <span>{draft.text.length.toLocaleString()} of 4,000 characters</span>
          <button type="button" className="btn btn-primary" onClick={onCheck} disabled={!canCheck}>Check copy</button>
        </div>
        {!ready && <p className="small-note">Checking opens once the server is running. Samples open now.</p>}
        {error && <p className="error-box" role="alert">{error}</p>}
      </div>
      {samples.length > 0 && (
        <div className="start" style={{ borderTop: "1px solid var(--line-soft)", paddingTop: 16, gap: 10 }}>
          <p style={{ fontSize: 14, fontWeight: 600 }}>Or open a sample review</p>
          <div className="samples-list">
            {samples.map((s) => (
              <button key={s.id} type="button" onClick={() => onOpenSample(s)}>
                <span>{s.title}</span>
                <span className="count">{s.nClaims} claims</span>
              </button>
            ))}
          </div>
          <p className="small-note">Samples open instantly. Live checks run on free model quotas, so each visitor gets 20 an hour.</p>
        </div>
      )}
    </div>
  );
}

export function ProofCard({ doc, sel, onSelect, onEdit }) {
  const seen = useRef(new Set());
  const arrived = new Set();
  for (const n of Object.keys(doc.reviews)) {
    if (!seen.current.has(n)) arrived.add(Number(n));
  }
  useEffect(() => {
    Object.keys(doc.reviews).forEach((n) => seen.current.add(n));
  });

  const parts = segments(doc.text, doc.claims);
  const labelText = (l) =>
    `the ${(l.products || [l.key]).join(" and ")} label, version ${l.version}${l.effective_time ? `, effective ${formatDate(l.effective_time)}` : ""}`;
  return (
    <article className="sheet" aria-labelledby="copy-title">
      <div className="sheet-head">
        <div className="sheet-title">
          <h2 id="copy-title">{doc.title}</h2>
          {doc.source === "sample" && <span className="chip">Synthetic test copy</span>}
        </div>
        <button type="button" className="btn" onClick={onEdit}>Edit copy</button>
      </div>
      {doc.note && doc.note !== "Synthetic test copy." && <p className="sample-note">{doc.note}</p>}
      <p className="proof">
        {doc.claims.length === 0
          ? doc.text
          : parts.map((p, i) => {
              if (!p.claim) return <span key={i}>{p.text}</span>;
              const n = p.claim.n;
              const s = statusOf(doc.reviews[n]);
              return (
                <a
                  key={i}
                  href="#claim-panel"
                  className={`claim-link tone-${s.tone}${arrived.has(n) && doc.source === "live" ? " arrived" : ""}`}
                  aria-current={n === sel ? "true" : "false"}
                  aria-label={`Claim ${n}, ${s.label}: ${p.text}`}
                  onClick={(e) => {
                    onSelect(n);
                    if (window.matchMedia("(min-width: 1100px)").matches) e.preventDefault();
                  }}
                >
                  {p.text}
                  <sup className="claim-mark">{n}</sup>
                </a>
              );
            })}
      </p>
      <p className="sheet-foot">
        {doc.claims.length > 0 ? `${doc.claims.length} claims found. ` : ""}
        {doc.labels.length ? `Checked against ${doc.labels.map(labelText).join(" and ")}.` : ""}
        {doc.ambiguous && doc.labels.length > 1
          ? " The drug named in the copy appears on more than one label, so every claim was checked against each. Pick a label at the top to narrow the check."
          : ""}
        {doc.splitBy === "sentences" ? " Claims were split by sentence because no model was available to split them." : ""}
      </p>
    </article>
  );
}
