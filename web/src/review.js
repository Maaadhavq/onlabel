// Turning server events into page state, shared by live reviews and the stored samples.

export const STATUS = {
  supported: { label: "Traced to label", tone: "traced" },
  needs_qualifier: { label: "Needs a qualifier", tone: "qualifier" },
  unsupported: { label: "Not in the label", tone: "absent" },
  contradicted: { label: "Conflicts with label", tone: "conflict" },
  off_label: { label: "Off-label", tone: "conflict" },
  needs_human_review: { label: "Reviewer decides", tone: "reviewer" },
};

export const PENDING = { label: "Checking", tone: "pending" };

export function statusOf(review) {
  return review ? STATUS[review.status] || { label: review.status, tone: "reviewer" } : PENDING;
}

const MODEL_NAMES = {
  "groq/gpt-oss-120b": "gpt-oss-120b on Groq",
  "groq/gpt-oss-20b": "gpt-oss-20b on Groq",
  "groq/qwen3.8-27b": "Qwen3.8 27B on Groq",
  "gemini/gemma-4-26b": "Gemma 4 26B on Google AI Studio",
  "ollama/llama3.1-8b": "Llama 3.1 8B on this machine",
  "ollama/qwen3-8b": "Qwen3 8B on this machine",
  "ollama/gemma4-e4b": "Gemma 4 E4B on this machine",
};

export const modelName = (key) => MODEL_NAMES[key] || key || "no model";

// Label text as a reader expects it. The parser marks superscripts with "^" so "m^2" and
// footnote marks survive, which reads oddly on a trademark sign; and a blank line inside a
// quote would otherwise be highlighted as an empty bar.
// A label's name as the API gives it (onlabel/data/corpus.py label_name): every brand on it,
// the one it is filed under first, device presentations ("MOUNJARO KWIKPEN") left out. Older
// stored samples carry only the product list.
export function labelName(label) {
  if (label.drug) return label.drug;
  const names = (label.products || []).filter(Boolean);
  if (!names.length) return (label.key || "").toUpperCase();
  const brands = names.filter((p) => !names.some((q) => p !== q && p.startsWith(`${q} `)));
  const key = (label.key || "").toLowerCase();
  return brands.sort((a, b) => Number(a.toLowerCase() !== key) - Number(b.toLowerCase() !== key)).join(" and ");
}

export const tidy = (text) => (text || "").replace(/\^([®™])/g, "$1").replace(/\n\s*\n/g, "\n");

export function emptyDoc(meta) {
  return {
    ...meta, // source, id, title, note, text, audience
    status: "starting",
    labels: [],
    ambiguous: false,
    claims: [],
    reviews: {},
    checks: [],
    injection: null,
    queuedAhead: 0,
    stats: null,
    error: null,
  };
}

export function applyEvent(doc, event, data) {
  switch (event) {
    case "queued":
      return { ...doc, status: "queued", queuedAhead: data.ahead };
    case "start":
      return { ...doc, status: "splitting", labels: data.labels || [], ambiguous: !!data.ambiguous, injection: data.injection || null };
    case "claims":
      return { ...doc, status: "checking", claims: data.claims || [], splitBy: data.split_by, splitModel: data.split_model, omitted: data.omitted || 0 };
    case "claim":
      return { ...doc, reviews: { ...doc.reviews, [data.n]: data.review } };
    case "document":
      return { ...doc, checks: data.checks || [] };
    case "done":
      return { ...doc, status: doc.status === "error" ? "error" : "done", stats: data };
    case "error":
      return { ...doc, status: "error", error: data.message || "The review stopped." };
    default:
      return doc;
  }
}

export function replay(meta, events) {
  return events.reduce((doc, ev) => applyEvent(doc, ev.event, ev.data), emptyDoc(meta));
}

// Text and claims interleaved in reading order, for the proof view.
export function segments(text, claims) {
  const out = [];
  let pos = 0;
  [...claims].sort((a, b) => a.start - b.start).forEach((c) => {
    if (c.start > pos) out.push({ text: text.slice(pos, c.start) });
    out.push({ text: text.slice(c.start, c.end), claim: c });
    pos = Math.max(pos, c.end);
  });
  if (pos < text.length) out.push({ text: text.slice(pos) });
  return out;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function attemptText(a) {
  const who = modelName(a.model);
  if (a.skipped) return `${who}: ${a.skipped === "no api key" ? "no key set" : a.skipped}`;
  if (a.rejected) return `${who}: answer rejected (${a.rejected})`;
  if (a.error) return `${who}: ${a.error}`;
  return `${who} answered${a.repaired ? " after one repair" : ""}`;
}

// The review's raw trace as the steps a reviewer reads in "How it decided".
export function traceSteps(review) {
  const steps = [];
  for (const t of review.trace || []) {
    if (t.step === "search_label") {
      const pinned = t.pinned_for_figures ? `; ${plural(t.pinned_for_figures, "excerpt")} pinned for the claim's figures` : "";
      const routed = t.routed_to?.length ? `; always includes ${t.routed_to.join(", ")}` : "";
      steps.push({ title: "Searched the label", detail: `${plural(t.n_hits, "excerpt")} ranked by meaning, keywords and figures${routed}${pinned}`, meta: `${t.ms} ms` });
    } else if (t.step === "judge") {
      const detail = t.source === "cache"
        ? `${modelName(t.model)}, replayed from the saved answer`
        : (t.attempts || []).map(attemptText).join(". ") || "No model was reachable";
      const secs = t.ms ? `${(t.ms / 1000).toFixed(1)} s` : "";
      steps.push({ title: "Asked the judge", detail, meta: [secs, t.tokens ? `${t.tokens.toLocaleString()} tokens` : ""].filter(Boolean).join(" · ") });
    } else if (t.step === "injection") {
      steps.push({ title: "Held for a reviewer", detail: `Found in the copy: ${t.findings.join("; ")}. No claim from it can be traced`, meta: "" });
    } else if (t.step === "guards") {
      const dropped = t.proposed_quotes - t.kept_quotes;
      steps.push({
        title: "Checked the quotes",
        detail: `${t.kept_quotes} of ${plural(t.proposed_quotes, "quote")} found in the label${dropped ? `; ${dropped} dropped` : ""}`,
        meta: `${t.ms} ms`,
      });
    }
  }
  const s = statusOf(review);
  const why = (review.violations || []).map((v) => v.replaceAll("_", " ")).join(", ");
  steps.push({ title: "Verdict", detail: why ? `${s.label}: ${why}` : s.label, meta: "" });
  return steps;
}

export function counts(doc) {
  const out = {};
  for (const c of doc.claims) {
    const tone = statusOf(doc.reviews[c.n]).label;
    out[tone] = (out[tone] || 0) + 1;
  }
  return out;
}

const SMALL_WORDS = new Set(["and", "or", "of", "in", "with", "for", "the", "to", "a", "an", "on", "at", "by"]);

// "14 CLINICAL STUDIES > 14.1 Weight Reduction ... Obesity" -> "14.1 Weight Reduction ... Obe…"
export function shortSection(path, max = 64) {
  let last = path.split(" > ").at(-1).trim();
  if (last === last.toUpperCase() && /[A-Z]/.test(last)) {
    last = last.toLowerCase().split(" ").map((w, i) => (i > 0 && SMALL_WORDS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
  }
  return last.length > max ? `${last.slice(0, max - 1).trimEnd()}…` : last;
}

// Word-level difference between a claim and its suggested rewrite (longest common subsequence).
export function wordDiff(before, after) {
  const a = before.split(/\s+/).filter(Boolean);
  const b = after.split(/\s+/).filter(Boolean);
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i].toLowerCase() === b[j].toLowerCase() ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  const push = (type, text) => {
    const prev = out.at(-1);
    if (prev && prev.type === type) prev.text += ` ${text}`;
    else out.push({ type, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i].toLowerCase() === b[j].toLowerCase()) { push("same", b[j]); i += 1; j += 1; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", a[i]); i += 1; }
    else { push("add", b[j]); j += 1; }
  }
  while (i < a.length) { push("del", a[i]); i += 1; }
  while (j < b.length) { push("add", b[j]); j += 1; }
  return out;
}

// Next claim after `from` (wrapping) whose verdict has this label; `from` itself if it is the only one.
export function nextWithStatus(doc, label, from) {
  const order = doc.claims.map((c) => c.n);
  const matches = order.filter((n) => statusOf(doc.reviews[n]).label === label);
  if (!matches.length) return from;
  return matches.find((n) => n > from) ?? matches[0];
}

// Everything a reviewer needs to file: verdicts, quotes, checks, decisions.
export function buildAudit(doc, decisions = {}, rewrites = {}) {
  return {
    tool: "OnLabel MLR pre-check",
    generated_at: new Date().toISOString(),
    source: doc.source === "sample" ? `sample: ${doc.title}` : "live check",
    audience: doc.audience,
    copy: doc.text,
    labels: doc.labels.map((l) => ({ key: l.key, products: l.products, set_id: l.set_id, version: l.version, effective: l.effective_time })),
    document_checks: doc.checks,
    claims_not_checked: doc.omitted || 0,
    claims: doc.claims.map((c) => {
      const r = doc.reviews[c.n];
      const rw = rewrites[c.n]?.data;
      return {
        n: c.n,
        text: c.text,
        span: [c.start, c.end],
        verdict: r ? statusOf(r).label : "not checked",
        model_verdict: r?.model_verdict ?? null,
        violations: r?.violations ?? [],
        reasoning: r?.reasoning ?? "",
        evidence: (r?.evidence ?? []).map((e) => ({ section: e.section_path, quote: e.quote, match: e.match, label_version: e.label_version, url: e.url })),
        checks: r?.checks ?? [],
        model: r?.model ?? null,
        tokens: r?.tokens ?? 0,
        suggested_wording: rw ? { text: rw.rewrite, verdict: statusOf(rw.review).label } : null,
        reviewer: decisions[c.n] ?? null,
      };
    }),
  };
}

export function formatDate(yyyymmdd) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return "";
  const d = new Date(`${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}
