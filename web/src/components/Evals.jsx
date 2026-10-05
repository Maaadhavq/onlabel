import { useState } from "react";
import summary from "../evals/summary.json";

// Every number on this page comes from summary.json, which evals/summarize.py builds from the
// committed reports. Nothing here is typed by hand.

const VERDICTS = [
  ["supported", "Traced"],
  ["needs_qualifier", "Needs qualifier"],
  ["unsupported", "Not in label"],
  ["contradicted", "Conflicts"],
  ["off_label", "Off-label"],
  ["needs_human_review", "Reviewer decides"],
];
const OPS = {
  faithful: "Restated faithfully",
  drop_qualifier: "Qualifier dropped",
  broaden: "Population broadened",
  inflate: "Figure inflated",
  superiority: "Superiority added",
  absolute: "Absolute added",
  deny_risk: "Risk denied",
  contradict: "Label contradicted",
  wrong_dose: "Dose or use changed",
};
const RETRIEVAL = [
  ["dense", "Meaning only (dense)"],
  ["bm25", "Keywords only (BM25)"],
  ["hybrid", "Both, fused (RRF)"],
  ["hybrid+figures", "+ figures pinned"],
  ["production", "+ governing sections"],
];
const REPORT = (name) => `${summary.repo}/reports/${name}.md`;

function Tip({ tip }) {
  if (!tip) return null;
  return (
    <div className="viz-tip" role="status" style={{ left: tip.x, top: tip.y }}>
      <strong>{tip.value}</strong>
      <span>{tip.label}</span>
    </div>
  );
}

// Hover and focus show the same tooltip; every value is also in the text or the table.
function useTip() {
  const [tip, setTip] = useState(null);
  const bind = (value, label) => ({
    tabIndex: 0,
    "aria-label": `${label}: ${value}`,
    onMouseMove: (e) => setTip({ value, label, x: e.clientX + 14, y: e.clientY + 14 }),
    onMouseLeave: () => setTip(null),
    onFocus: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      setTip({ value, label, x: r.right + 8, y: r.top });
    },
    onBlur: () => setTip(null),
  });
  return [tip, bind];
}

const of = (a, b) => `${a} of ${b}`;
const pct = (v) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);

function Kpis({ prod, retrieval, red }) {
  const on = prod?.guards_on;
  const tiles = [];
  if (on) {
    const scope = prod.split === "all" ? "" : ` (${prod.split} split)`;
    tiles.push({ label: `Violative claims traced${scope}`, value: of(on.false_approvals, on.n_violative), note: prod.name });
    tiles.push({ label: `Faithful claims traced${scope}`, value: of(on.traced_faithful, on.n_faithful), note: "the rest go to a reviewer" });
  }
  const prodRetrieval = retrieval?.configs?.production;
  if (prodRetrieval) tiles.push({ label: "Label text in front of the judge", value: pct(prodRetrieval.all), note: `${retrieval.n_claims} claims, section chunks` });
  if (red) tiles.push({ label: "Injection attacks that got a claim traced", value: of(red.layers.final, red.answered), note: `${red.name}, every layer on` });
  return (
    <div className="kpis">
      {tiles.map((t) => (
        <div className="kpi" key={t.label}>
          <span className="kpi-label">{t.label}</span>
          <span className="kpi-value">{t.value}</span>
          <span className="kpi-note">{t.note}</span>
        </div>
      ))}
    </div>
  );
}

// Guards off (hollow) to guards on (filled): violative claims each model's run traced.
function Dumbbell({ off, on, max, bind }) {
  const W = 220;
  const H = 26;
  const pad = 10;
  const x = (v) => pad + (max ? (v / max) * (W - 2 * pad) : 0);
  return (
    <svg className="dumbbell" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
      aria-label={`${off} traced with the guards off, ${on} with them on`}>
      <line x1={pad} x2={W - pad} y1={H / 2} y2={H / 2} className="db-track" />
      {off !== on && <line x1={x(on)} x2={x(off)} y1={H / 2} y2={H / 2} className="db-span" />}
      <g {...bind(String(off), "Traced with the guards off")}>
        <circle cx={x(off)} cy={H / 2} r={12} className="db-hit" />
        <circle cx={x(off)} cy={H / 2} r={5} className="db-off" />
      </g>
      <g {...bind(String(on), "Traced with the guards on")}>
        <circle cx={x(on)} cy={H / 2} r={12} className="db-hit" />
        <circle cx={x(on)} cy={H / 2} r={5} className="db-on" />
      </g>
    </svg>
  );
}

function ModelTable({ runs, bind }) {
  const max = Math.max(1, ...runs.map((r) => r.guards_off.false_approvals));
  return (
    <div className="table-scroll">
      <table className="eval-table">
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Claims</th>
            <th scope="col">Violative claims traced</th>
            <th scope="col" className="num">Guards off</th>
            <th scope="col" className="num">Guards on</th>
            <th scope="col" className="num">Faithful traced</th>
            <th scope="col" className="num">To a reviewer</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.report}>
              <th scope="row">{r.name}</th>
              <td>{r.split === "all" ? "all" : r.split} · {r.n}</td>
              <td><Dumbbell off={r.guards_off.false_approvals} on={r.guards_on.false_approvals} max={max} bind={bind} /></td>
              <td className="num">{of(r.guards_off.false_approvals, r.guards_off.n_violative)}</td>
              <td className="num strong">{of(r.guards_on.false_approvals, r.guards_on.n_violative)}</td>
              <td className="num">{of(r.guards_on.traced_faithful, r.guards_on.n_faithful)}</td>
              <td className="num">{pct(r.guards_on.human_review)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="legend-row" aria-hidden="true">
        <span className="key"><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" className="db-off" /></svg> guards off (the model's own verdict)</span>
        <span className="key"><svg width="12" height="12"><circle cx="6" cy="6" r="4.5" className="db-on" /></svg> guards on (what the reviewer shows)</span>
      </p>
    </div>
  );
}

function OutcomeGrid({ run, bind }) {
  const rows = Object.entries(run.by_op);
  const max = Math.max(1, ...rows.flatMap(([, t]) => VERDICTS.map(([v]) => t[v] || 0)));
  const step = (n) => (n === 0 ? 0 : Math.min(5, Math.ceil((n / max) * 5)));
  return (
    <div className="table-scroll">
      <table className="eval-table grid-table">
        <thead>
          <tr>
            <th scope="col">Built as</th>
            {VERDICTS.map(([v, label]) => <th key={v} scope="col" className="num">{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(([op, t]) => (
            <tr key={op}>
              <th scope="row">{OPS[op] || op} <span className="dim">· {t.n}</span></th>
              {VERDICTS.map(([v, label]) => {
                const n = t[v] || 0;
                const bad = op !== "faithful" && v === "supported" && n > 0;
                return (
                  <td key={v} className={`cell heat-${step(n)}${bad ? " cell-bad" : ""}`}
                    {...(n ? bind(String(n), `${OPS[op] || op} → ${label}`) : {})}>
                    {n || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RetrievalBars({ section, fixed, bind }) {
  const W = 560;
  const label = 190;
  const bar = 12;
  const gap = 2;
  const rowH = 2 * bar + gap + 16;
  const H = RETRIEVAL.length * rowH;
  const x = (v) => (W - label - 46) * v;
  return (
    <figure className="bars-figure">
      <svg viewBox={`0 0 ${W} ${H}`} className="bars" role="img" aria-label="Share of claims whose label text is among the first five excerpts, by search configuration">
        {RETRIEVAL.map(([key, name], i) => {
          const y = i * rowH + 4;
          const a = section.configs[key]?.["hit@5"];
          const b = fixed?.configs[key]?.["hit@5"];
          return (
            <g key={key}>
              <text x={label - 10} y={y + bar + 2} className="bar-label" textAnchor="end">{name}</text>
              <line x1={label} x2={label} y1={y - 2} y2={y + 2 * bar + gap + 2} className="bar-base" />
              {a != null && (
                <g {...bind(pct(a), `${name}, section chunks`)}>
                  <rect x={label} y={y - 1} width={x(1)} height={bar + 2} className="bar-hit" />
                  <path d={roundEnd(label, y, x(a), bar)} className="bar-a" />
                  <text x={label + x(a) + 6} y={y + bar - 2} className="bar-value">{pct(a)}</text>
                </g>
              )}
              {b != null && (
                <g {...bind(pct(b), `${name}, fixed windows`)}>
                  <rect x={label} y={y + bar + gap - 1} width={x(1)} height={bar + 2} className="bar-hit" />
                  <path d={roundEnd(label, y + bar + gap, x(b), bar)} className="bar-b" />
                  <text x={label + x(b) + 6} y={y + 2 * bar + gap - 2} className="bar-value dim">{pct(b)}</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend-row">
        <span className="key"><span className="swatch-a" /> section-aware chunks ({section.n_chunks})</span>
        {fixed && <span className="key"><span className="swatch-b" /> fixed 180-word windows ({fixed.n_chunks})</span>}
      </figcaption>
    </figure>
  );
}

// A bar with a 4px rounded data end and a square baseline.
function roundEnd(x0, y, w, h) {
  const r = Math.min(4, w / 2, h / 2);
  if (w <= 0) return "";
  return `M${x0},${y} H${x0 + w - r} Q${x0 + w},${y} ${x0 + w},${y + r} V${y + h - r} Q${x0 + w},${y + h} ${x0 + w - r},${y + h} H${x0} Z`;
}

const LAYERS = [
  ["model_verdict", "The model alone"],
  ["after_guards", "+ grounding and figure guards"],
  ["final", "+ injection check (what the reviewer shows)"],
];

function RedTeam({ runs }) {
  const d = runs[0].detector; // the detectors read the copy, so every run scores them the same
  const both = d["patterns+prompt_guard"] || d.patterns;
  return (
    <div className="table-scroll">
      <table className="eval-table">
        <thead>
          <tr>
            <th scope="col">Attacks that got the violative claim traced</th>
            {runs.map((r) => <th key={r.report} scope="col" className="num">{r.name}<br /><span className="dim">{r.answered} answered</span></th>)}
          </tr>
        </thead>
        <tbody>
          {LAYERS.map(([key, label]) => (
            <tr key={key}>
              <th scope="row">{label}</th>
              {runs.map((r) => (
                <td key={r.report} className={`num${key === "final" ? " strong" : ""}`}>{of(r.layers[key], r.answered)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <table className="eval-table">
        <thead>
          <tr><th scope="col">Detector</th><th scope="col" className="num">Attacks flagged</th><th scope="col" className="num">Benign lines flagged</th></tr>
        </thead>
        <tbody>
          <tr><th scope="row">Patterns written for MLR copy</th><td className="num">{of(d.patterns.attacks_flagged, d.patterns.n_attacks)}</td><td className="num">{of(d.patterns.benign_flagged, d.patterns.n_benign)}</td></tr>
          {d.prompt_guard_alone && (
            <tr><th scope="row">Llama Prompt Guard 2 alone</th><td className="num">{of(d.prompt_guard_alone.attacks_flagged, d.patterns.n_attacks)}</td><td className="num">{of(d.prompt_guard_alone.benign_flagged, d.patterns.n_benign)}</td></tr>
          )}
          <tr><th scope="row">Both (what the API runs)</th><td className="num strong">{of(both.attacks_flagged, both.n_attacks)}</td><td className="num strong">{of(both.benign_flagged, both.n_benign)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

export default function Evals() {
  const [tip, bind] = useTip();
  const b = summary.bench;
  const runs = summary.verify;
  const prod = runs.find((r) => r.model === "groq/gpt-oss-120b") || runs[0];
  const section = summary.retrieval.section;
  const fixed = summary.retrieval.fixed;
  const reds = summary.redteam;
  // Headline: the hosted run that answered the most attacks.
  const red = [...reds].sort((a, b) => Number(a.model.startsWith("ollama/")) - Number(b.model.startsWith("ollama/"))
    || b.answered - a.answered)[0];
  const stopped = runs.flatMap((r) => r.stopped_by_guards.map((c) => ({ ...c, model: r.name })));

  return (
    <main className="evals">
      <article className="sheet evals-sheet">
        <header className="evals-head">
          <h1>How OnLabel was tested</h1>
          <p className="lede">
            {b.claims} claims written from {b.cards} fact cards across {b.labels} FDA labels. Each card holds label text that code
            checks word for word against the label. Each claim's expected verdict comes from how it was built, never from a model:
            {" "}{b.faithful} restate the label faithfully and {b.violative} break it in a known way.
          </p>
          <Kpis prod={prod} retrieval={section} red={red} />
        </header>

        <section aria-labelledby="ev-approve">
          <h2 id="ev-approve">Would it trace a violation?</h2>
          <p>
            A violative claim shown as traced is the failure the tool exists to prevent. Guards off is the model's own verdict;
            guards on adds the plain-code checks (every quote found in the label, every figure in the quotes).
            The test split's {b.test} claims come from six ingredients nobody looked at while the prompts were written.
          </p>
          <ModelTable runs={runs} bind={bind} />
        </section>

        {prod && (
          <section aria-labelledby="ev-grid">
            <h2 id="ev-grid">What each kind of claim became</h2>
            <p>{prod.name}, {prod.split} split. Darker cells hold more claims; a count in the Traced column outside the first row is a false approval.</p>
            <OutcomeGrid run={prod} bind={bind} />
          </section>
        )}

        {section && (
          <section aria-labelledby="ev-retrieval">
            <h2 id="ev-retrieval">Does the right label text reach the judge?</h2>
            <p>
              Share of claims whose governing label text is among the first five excerpts. With the governing sections routed in,
              the judge sees up to six excerpts, and {pct(section.configs.production.all)} of claims have their label text among them.
            </p>
            <RetrievalBars section={section} fixed={fixed} bind={bind} />
          </section>
        )}

        {red && (
          <section aria-labelledby="ev-red">
            <h2 id="ev-red">Can the copy talk its way past the reviewer?</h2>
            <p>
              {red.n_attacks} attacks wrap a violative claim in an instruction to trace it: a fake system line, a verdict
              object, hidden HTML, base64, another language, a claimed MLR sign-off. Eighteen ordinary copy lines full of
              imperatives measure false alarms. The patterns and the attacks have the same author, so the pattern rate is an upper bound.
            </p>
            <RedTeam runs={reds} />
          </section>
        )}

        <section aria-labelledby="ev-wrong">
          <h2 id="ev-wrong">What went wrong, kept on the record</h2>
          <ul className="findings">
            {runs.flatMap((r) => r.false_approvals.map((c) => (
              <li key={`${r.report}-${c.id}`}><strong>{r.name} traced a violative claim</strong> ({OPS[c.op] || c.op}): “{c.text}”</li>
            )))}
            {stopped.slice(0, 4).map((c) => (
              <li key={`stop-${c.model}-${c.id}`}><strong>{c.model} called this supported; the guards held it</strong> ({OPS[c.op] || c.op}): “{c.text}”</li>
            ))}
            {runs.filter((r) => r.unanswered).map((r) => {
              const blocked = Object.entries(r.unanswered_reasons).filter(([k]) => k.includes("RECITATION")).reduce((a, [, v]) => a + v, 0);
              return (
                <li key={`un-${r.report}`}>
                  <strong>{r.name} gave no usable answer for {r.unanswered} claims.</strong>{" "}
                  {blocked > 0 && <>{blocked} were blocked by Google's recitation filter, which blanks answers that quote source text word for word, the one thing a judge of label claims has to do; </>}
                  the rest were cut off mid-answer or malformed. Those claims went to a reviewer.
                </li>
              );
            })}
            <li><strong>The holdout of claims FDA cited in its 2024–26 letters is not built yet.</strong> It needs a person to verify each extracted claim; the synthetic set shows whether known shapes of violation are caught, not how real copy behaves.</li>
          </ul>
        </section>

        <footer className="evals-foot">
          Generated {summary.generated} from the committed reports by <code>evals/summarize.py</code>. Read{" "}
          <a href={`${summary.repo}/EVALS.md`} target="_blank" rel="noreferrer">EVALS.md</a>, the per-claim{" "}
          <a href={REPORT(prod ? prod.report : "")} target="_blank" rel="noreferrer">verification report</a>, or rerun it
          without keys from the committed answer cache.
        </footer>
      </article>
      <Tip tip={tip} />
    </main>
  );
}
