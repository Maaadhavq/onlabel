import { useEffect, useRef } from "react";
import { formatDate, labelName, segments, statusOf } from "../review.js";
import { Download } from "./icons.jsx";

const MAX_CHARS = 4000;

export function EditorCard({ labels, draft, setDraft, onCheck, canCheck, busy, samples, onOpenSample, error, ready }) {
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
        <div className="editor-row">
          <label className="field-label" htmlFor="label-pick">Label</label>
          <select id="label-pick" className="select" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })}>
            <option value="">Detect from the copy</option>
            {labels.map((l) => (
              <option key={l.key} value={l.key}>{l.drug}{l.generic ? ` (${l.generic})` : ""}, version {l.version}</option>
            ))}
          </select>
          <span className="field-label" id="audience-label">Audience</span>
          <div className="seg" role="group" aria-labelledby="audience-label">
            {[["consumer", "Consumer"], ["hcp", "HCP"]].map(([value, text]) => (
              <button key={value} type="button" aria-pressed={draft.audience === value} onClick={() => setDraft({ ...draft, audience: value })}>
                {text}
              </button>
            ))}
          </div>
        </div>
        <div className="editor-foot">
          <span>{draft.text.length.toLocaleString()} of 4,000 characters</span>
          <button type="button" className="btn btn-primary" onClick={onCheck} disabled={!canCheck}>
            {busy ? "Checking…" : "Check copy"}
          </button>
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

export function ProofCard({ doc, sel, onSelect, onEdit, onDownload, hoverN, setHoverN }) {
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
    `the ${labelName(l)} label, version ${l.version}${l.effective_time ? `, effective ${formatDate(l.effective_time)}` : ""}`;
  const finished = doc.status === "done" && doc.claims.length > 0;

  return (
    <article className="sheet" aria-labelledby="copy-title">
      <div className="sheet-head">
        <div className="sheet-title">
          <h2 id="copy-title">{doc.title}</h2>
          {doc.source === "sample" && <span className="chip">Synthetic test copy</span>}
        </div>
        <div className="sheet-actions">
          <button type="button" className="btn btn-small" onClick={onDownload} disabled={!finished} title="Every verdict, quote, check and your decisions, as a JSON audit file">
            <Download /> Download review
          </button>
          <button type="button" className="btn btn-small" onClick={onEdit}>Edit copy</button>
        </div>
      </div>
      {doc.note && doc.note !== "Synthetic test copy." && <p className="sample-note">{doc.note}</p>}
      {doc.injection?.flagged && (
        <div className="error-box" role="alert">
          <strong>This copy contains instructions aimed at the reviewer</strong>
          {" "}({doc.injection.findings.filter((f) => f.flags).map((f) => f.why).join("; ")}). Every claim is still
          checked, but none can be traced: an approval the copy asks for is not an approval.
        </div>
      )}
      <p className="proof">
        {doc.claims.length === 0
          ? doc.text
          : parts.map((p, i) => {
              if (!p.claim) return <span key={i}>{p.text}</span>;
              const n = p.claim.n;
              const s = statusOf(doc.reviews[n]);
              const cls = ["claim-link", `tone-${s.tone}`];
              if (arrived.has(n) && doc.source === "live") cls.push("arrived");
              if (hoverN === n) cls.push("is-hover");
              return (
                <a
                  key={i}
                  href="#claim-panel"
                  className={cls.join(" ")}
                  aria-current={n === sel ? "true" : "false"}
                  aria-label={`Claim ${n}, ${s.label}: ${p.text}`}
                  onMouseEnter={() => setHoverN(n)}
                  onMouseLeave={() => setHoverN(null)}
                  onFocus={() => setHoverN(n)}
                  onBlur={() => setHoverN(null)}
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
          ? " The drug named in the copy appears on more than one label, so every claim was checked against each. Pick a label to narrow the check."
          : ""}
        {doc.splitBy === "sentences" ? " Claims were split by sentence because no model was available to split them." : ""}
      </p>
    </article>
  );
}
