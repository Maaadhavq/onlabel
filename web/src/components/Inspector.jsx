import { useEffect, useState } from "react";
import { STATUS, modelName, shortSection, statusOf, tidy, traceSteps, wordDiff } from "../review.js";
import { Check, ChevronLeft, ChevronRight, Cross } from "./icons.jsx";

const MATCH = {
  exact: ["exact quote", "Found word for word in the label."],
  normalized: ["exact quote", "Found word for word once spacing, dashes and bullet marks were evened out."],
  elided: ["shortened quote", "The model shortened the quote with an ellipsis; every part was found, in order, in the label. The full passage is shown."],
  stitched: ["quote skips lines", "The model quoted parts of this passage and left out whole lines between them, such as other list items or table rows. Every part was found word for word; the full passage is shown."],
  fuzzy: ["near match", "Found with small wording differences; quotes with figures never match this way."],
};

export const TABS = [
  ["evidence", "Label evidence"],
  ["checks", "What the checks caught"],
  ["trace", "How it decided"],
];

export default function Inspector({ doc, sel, onSelect, tab, setTab, rewrite, onRewrite, canRewrite, rewriteUnavailable, decision, onDecide }) {
  if (!doc) {
    return (
      <div className="inspector">
        <div className="empty-insp">
          <h2>Claims and their label evidence appear here</h2>
          <p>Open a sample or paste copy and check it. Each claim gets a verdict, the exact label text behind it, and a record of how it was decided. You make the final call on each one.</p>
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
                The model said {STATUS[review.model_verdict]?.label.toLowerCase() || review.model_verdict}; the checks changed that.
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
            {TABS.map(([id, label], i) => (
              <button key={id} type="button" role="tab" id={`tab-${id}`} aria-selected={tab === id} aria-controls={`panel-${id}`}
                aria-keyshortcuts={String(i + 1)} onClick={() => setTab(id)}>
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
            {doc.status === "done" && <Decision key={n} n={n} review={review} decision={decision} onDecide={onDecide} />}
            <div className="foot-row">
              <p className="kbd-hint">
                <span><kbd>J</kbd> <kbd>K</kbd> or <kbd>←</kbd> <kbd>→</kbd> move between claims</span>
                <span><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> switch tabs</span>
              </p>
              {url && <a href={url} target="_blank" rel="noreferrer" style={{ fontSize: 14, fontWeight: 600 }}>Open the label on DailyMed</a>}
            </div>
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
  const [chip, detail] = MATCH[e.match] || [e.match, ""];
  return (
    <figure className="excerpt-fig">
      <figcaption className="excerpt-cap" title={e.section_path}>
        <span>
          <span className="drug">{e.drug} v{e.label_version}</span>
          <span className="where">{shortSection(e.section_path)}</span>
        </span>
        <span className="match-chip" title={detail}>{chip}</span>
      </figcaption>
      {e.kind === "table" && e.table ? (
        <LabelTable table={e.table} />
      ) : e.kind === "boxed" ? (
        <div className="boxed">
          <p className="boxed-title">{e.section_path.split(" > ")[0]}</p>
          <p>{tidy(e.before)}<mark>{tidy(e.quote)}</mark>{tidy(e.after)}</p>
        </div>
      ) : (
        <p className="excerpt">{tidy(e.before)}<mark>{tidy(e.quote)}</mark>{tidy(e.after)}</p>
      )}
    </figure>
  );
}

const COLLAPSED_ROWS = 6;

function LabelTable({ table }) {
  const [full, setFull] = useState(false);
  const width = Math.max(...[...table.header, ...table.rows].map((r) => r.length));
  const span = (row, i) => (row.length < width && i > 0 ? Math.max(1, Math.round((width - 1) / (row.length - 1))) : 1);
  const collapsible = table.rows.length > COLLAPSED_ROWS;
  const indexed = table.rows.map((row, i) => ({ row, i }));
  const quoted = indexed.filter(({ i }) => table.highlight.includes(i));
  const shown = !collapsible || full ? indexed : (quoted.length ? quoted : indexed.slice(0, 4));
  return (
    <div className="table-wrap">
      <table className="label-table">
        {table.caption && <caption>{tidy(table.caption)}</caption>}
        <thead>
          {table.header.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <th key={i} scope={span(row, i) > 1 ? "colgroup" : "col"} colSpan={span(row, i)}>{tidy(cell)}</th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {shown.map(({ row, i: r }) => (
            <tr key={r} className={table.highlight.includes(r) ? "hl" : undefined}>
              {row.map((cell, i) =>
                i === 0 ? <th key={i} scope="row" style={{ fontWeight: 400 }}>{tidy(cell)}</th> : <td key={i}>{tidy(cell)}</td>,
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {collapsible && (
        <button type="button" className="table-toggle" aria-expanded={full} onClick={() => setFull((f) => !f)}>
          {full ? "Show only the quoted rows" : `Show the full table (${table.rows.length} rows)`}
        </button>
      )}
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

function Diff({ before, after }) {
  return (
    <p className="diff" aria-label="What changed from the original claim">
      {wordDiff(before, after).map((p, i) => {
        const text = `${p.text} `;
        if (p.type === "del") return <del key={i}>{text}</del>;
        if (p.type === "add") return <ins key={i}>{text}</ins>;
        return <span key={i}>{text}</span>;
      })}
    </p>
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
      <div className="rewrite-box">
        <p className="rewrite-label">Suggested on-label wording</p>
        <p className="rewrite-text">{r.rewrite}</p>
        <Diff before={review.claim} after={r.rewrite} />
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
            className="btn btn-blue btn-small"
            onClick={() => navigator.clipboard?.writeText(r.rewrite).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); })}
          >
            {copied ? "Copied" : "Copy wording"}
          </button>
          <button type="button" className="btn btn-small" onClick={() => setHidden(true)}>Hide</button>
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

const CHOICES = Object.entries(STATUS).filter(([key]) => key !== "needs_human_review");

function Decision({ n, review, decision, onDecide }) {
  const [changing, setChanging] = useState(false);
  const [status, setStatus] = useState(decision?.status || review.status);
  const [note, setNote] = useState(decision?.note || "");
  useEffect(() => { setChanging(false); }, [n]);

  if (decision && !changing) {
    const label = statusOf({ status: decision.status }).label;
    return (
      <div className="decision">
        <div className="decision-done">
          <Check />
          <span>
            {decision.choice === "agree" ? `You agreed: ${label.toLowerCase()}.` : `You changed the verdict to ${label.toLowerCase()}.`}
            {decision.note ? ` Note: ${decision.note}` : ""}
          </span>
        </div>
        <div className="decision-buttons">
          <button type="button" className="btn btn-small" onClick={() => setChanging(true)}>Edit decision</button>
          <button type="button" className="btn btn-small" onClick={() => onDecide(n, null)}>Undo</button>
        </div>
      </div>
    );
  }
  return (
    <div className="decision">
      <div className="decision-head">
        <span className="decision-title">Your decision on claim {n}</span>
        <div className="decision-buttons">
          <button type="button" className="btn btn-small" onClick={() => onDecide(n, { choice: "agree", status: review.status, note })}>
            Agree with the verdict
          </button>
          <button type="button" className="btn btn-small" aria-pressed={changing} onClick={() => setChanging((c) => !c)}>
            Change the verdict
          </button>
        </div>
      </div>
      {changing && (
        <>
          <label className="field-label" htmlFor={`decision-status-${n}`}>Your verdict</label>
          <select id={`decision-status-${n}`} className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
            {CHOICES.map(([key, v]) => <option key={key} value={key}>{v.label}</option>)}
          </select>
          <label className="field-label" htmlFor={`decision-note-${n}`}>Note for the file (optional)</label>
          <textarea id={`decision-note-${n}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why you changed it, or what the copy needs." />
          <div className="decision-buttons">
            <button type="button" className="btn btn-primary btn-small" onClick={() => { onDecide(n, { choice: status === review.status ? "agree" : "change", status, note }); setChanging(false); }}>
              Save decision
            </button>
          </div>
        </>
      )}
    </div>
  );
}
