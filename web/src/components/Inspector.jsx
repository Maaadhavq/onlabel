import { useState } from "react";
import { STATUS, modelName, statusOf, traceSteps } from "../review.js";
import { Check, ChevronLeft, ChevronRight, Cross } from "./icons.jsx";

const MATCH = {
  exact: "exact match",
  normalized: "exact after spacing and dashes evened out",
  elided: "shortened quote, every part found",
  fuzzy: "near match",
};

const TABS = [
  ["evidence", "Label evidence"],
  ["checks", "What the checks caught"],
  ["trace", "How it decided"],
];

export default function Inspector({ doc, sel, onSelect, tab, setTab, rewrite, onRewrite, canRewrite, rewriteUnavailable }) {
  if (!doc) {
    return (
      <div className="inspector">
        <div className="empty-insp">
          <h2>Claims and their label evidence appear here</h2>
          <p>Open a sample or paste copy and check it. Each claim gets a verdict, the exact label text behind it, and a record of how it was decided.</p>
        </div>
      </div>
    );
  }
  if (doc.status === "error" && doc.claims.length === 0) {
    return (
      <div className="inspector">
        <div className="empty-insp">
          <h2>The check did not run</h2>
          <p>{doc.error}</p>
        </div>
      </div>
    );
  }
  if (doc.claims.length === 0) {
    return (
      <div className="inspector">
        <div className="empty-insp">
          <h2>{doc.status === "done" ? "No claims found" : "Finding the claims…"}</h2>
          <p>{doc.status === "done" ? "Nothing in this copy states a benefit, risk, use or comparison to check." : "The copy is being split into the claims an MLR reviewer would check."}</p>
        </div>
      </div>
    );
  }

  const n = Math.min(Math.max(sel, 1), doc.claims.length);
  const claim = doc.claims.find((c) => c.n === n);
  const review = doc.reviews[n];
  const s = statusOf(review);
  const total = doc.claims.length;
  const url = review?.evidence?.[0]?.url || (doc.labels[0] && `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${doc.labels[0].set_id}`);

  return (
    <div className="inspector">
      <div className="insp-head">
        <div className="insp-top">
          <h2 className="claim-count">Claim {n} of {total}</h2>
          <div className="insp-nav">
            <button type="button" className="icon-btn" aria-label="Previous claim" onClick={() => onSelect(n === 1 ? total : n - 1)}><ChevronLeft /></button>
            <button type="button" className="icon-btn" aria-label="Next claim" onClick={() => onSelect(n === total ? 1 : n + 1)}><ChevronRight /></button>
          </div>
        </div>
        <p className="claim-text">{claim.text}</p>
        <div className="pills">
          <span className={`status-pill tone-${s.tone}`}>{s.label}</span>
          {(review?.violations || []).map((v) => (
            <span key={v} className="tag">{v.replaceAll("_", " ")}</span>
          ))}
        </div>
        {review ? (
          <>
            <p className="why">{review.reasoning}</p>
            {review.model_verdict && review.model_verdict !== review.status && (
              <p className="model-said">
                The model said {STATUS[review.model_verdict]?.label.toLowerCase() || review.model_verdict}; the checks below changed that.
              </p>
            )}
          </>
        ) : (
          <p className="status-line"><span className="spinner" aria-hidden="true" />Checking this claim against the label…</p>
        )}
      </div>

      {review && (
        <>
          <div className="tabs" role="tablist" aria-label="Claim details">
            {TABS.map(([id, label]) => (
              <button key={id} type="button" role="tab" id={`tab-${id}`} aria-selected={tab === id} aria-controls={`panel-${id}`} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </div>
          <div className="panel" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {tab === "evidence" && <EvidenceList review={review} />}
            {tab === "checks" && <Checks review={review} />}
            {tab === "trace" && <Trace review={review} />}
          </div>
          <div className="insp-foot">
            <RewriteArea review={review} rewrite={rewrite} onRewrite={onRewrite} canRewrite={canRewrite} unavailable={rewriteUnavailable} />
            {url && <a href={url} target="_blank" rel="noreferrer" style={{ fontSize: 14, fontWeight: 600 }}>Open the label on DailyMed</a>}
          </div>
        </>
      )}
    </div>
  );
}

function EvidenceList({ review }) {
  if (!review.evidence.length) {
    return (
      <p className="small-note">
        {review.status === "unsupported"
          ? "Nothing in the label supports this claim, so there is no passage to show."
          : "No quote survived the checks. See What the checks caught."}
      </p>
    );
  }
  return review.evidence.map((e, i) => <Evidence key={`${e.chunk_id}-${i}`} e={e} />);
}

function Evidence({ e }) {
  return (
    <figure className="excerpt-fig">
      <figcaption className="excerpt-cap">
        <span>{e.drug} v{e.label_version} · {e.section_path}</span>
        <span>{MATCH[e.match] || e.match}</span>
      </figcaption>
      {e.kind === "table" && e.table ? (
        <LabelTable table={e.table} />
      ) : e.kind === "boxed" ? (
        <div className="boxed">
          <p className="boxed-title">{e.section_path.split(" > ")[0]}</p>
          <p>{e.before}<mark>{e.quote}</mark>{e.after}</p>
        </div>
      ) : (
        <p className="excerpt">{e.before}<mark>{e.quote}</mark>{e.after}</p>
      )}
    </figure>
  );
}

function LabelTable({ table }) {
  const width = Math.max(...[...table.header, ...table.rows].map((r) => r.length));
  const span = (row, i) => (row.length < width && i > 0 ? Math.max(1, Math.round((width - 1) / (row.length - 1))) : 1);
  return (
    <div className="table-wrap">
      <table className="label-table">
        {table.caption && <caption>{table.caption}</caption>}
        <thead>
          {table.header.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <th key={i} scope={span(row, i) > 1 ? "colgroup" : "col"} colSpan={span(row, i)}>{cell}</th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r} className={table.highlight.includes(r) ? "hl" : undefined}>
              {row.map((cell, i) =>
                i === 0 ? <th key={i} scope="row" style={{ fontWeight: 400 }}>{cell}</th> : <td key={i}>{cell}</td>,
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checks({ review }) {
  return (
    <>
      <ul className="checks">
        {review.checks.map((k, i) => (
          <li key={i}>
            <span className={`check-icon ${k.ok ? "ok" : "catch"}`}>{k.ok ? <Check /> : <Cross />}</span>
            <span style={{ paddingTop: 1 }}>{k.text}</span>
          </li>
        ))}
      </ul>
      <p className="small-note">
        These checks are plain code with no model involved. A quote counts only if it is found in the label, and a claim
        traced to the label must show every figure it states inside its quotes.
      </p>
    </>
  );
}

function Trace({ review }) {
  return (
    <ol className="trace">
      {traceSteps(review).map((st, i) => (
        <li key={i}>
          <span className="n">{i + 1}</span>
          <span className="body">
            <span className="title">{st.title}</span>
            <span className="detail">{st.detail}</span>
          </span>
          <span className="meta">{st.meta}</span>
        </li>
      ))}
    </ol>
  );
}

function RewriteArea({ review, rewrite, onRewrite, canRewrite, unavailable }) {
  const [copied, setCopied] = useState(false);
  const [hidden, setHidden] = useState(false);
  if (review.status === "supported") return <p className="traced-note">Traced to the label. No change needed.</p>;

  if (rewrite?.state === "done" && !hidden) {
    const r = rewrite.data;
    const traced = r.review?.status === "supported";
    const s = statusOf(r.review);
    return (
      <div className={`rewrite-box${traced ? "" : " unchecked"}`}>
        <p className="rewrite-label">Suggested on-label wording</p>
        <p className="rewrite-text">{r.rewrite}</p>
        <p className="rewrite-check">
          {traced ? <Check /> : <Cross />}
          <span>
            {traced
              ? `Checked against the label: traced. Written by ${modelName(r.model).split(" on ")[0]}, checked by the normal pipeline.`
              : `Checked against the label: ${s.label.toLowerCase()}. Edit it before use.`}
          </span>
        </p>
        <div className="foot-row" style={{ justifyContent: "flex-start" }}>
          <button
            type="button"
            className="btn btn-blue"
            onClick={() => navigator.clipboard?.writeText(r.rewrite).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); })}
          >
            {copied ? "Copied" : "Copy wording"}
          </button>
          <button type="button" className="btn" onClick={() => setHidden(true)}>Hide</button>
        </div>
      </div>
    );
  }
  return (
    <div className="foot-row">
      {rewrite?.state === "loading" ? (
        <p className="status-line"><span className="spinner" aria-hidden="true" />Writing on-label wording, then checking it against the label…</p>
      ) : (
        <button type="button" className="btn btn-primary" disabled={!canRewrite} onClick={() => { setHidden(false); onRewrite(); }}>
          Suggest on-label wording
        </button>
      )}
      {rewrite?.state === "error" && <p className="small-note" role="alert">{rewrite.error}</p>}
      {unavailable && <p className="small-note">{unavailable}</p>}
    </div>
  );
}
