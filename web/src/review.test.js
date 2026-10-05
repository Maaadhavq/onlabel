import { test } from "node:test";
import assert from "node:assert/strict";
import { applyEvent, emptyDoc, replay, segments, statusOf, traceSteps } from "./review.js";

const TEXT = "Intro. Claim one here. Middle. Claim two here. End.";
const CLAIMS = [
  { n: 2, text: "Claim two here.", start: 31, end: 46 },
  { n: 1, text: "Claim one here.", start: 7, end: 22 },
];

test("segments interleave text and claims in reading order", () => {
  const parts = segments(TEXT, CLAIMS);
  assert.deepEqual(parts.map((p) => p.claim?.n ?? null), [null, 1, null, 2, null]);
  assert.equal(parts.map((p) => p.text).join(""), TEXT);
});

test("events build the document state the page renders", () => {
  const doc = replay({ source: "sample", id: "s", text: TEXT }, [
    { event: "start", data: { labels: [{ key: "wegovy" }] } },
    { event: "claims", data: { claims: CLAIMS, split_by: "model" } },
    { event: "claim", data: { n: 1, review: { status: "off_label" } } },
    { event: "document", data: { checks: [{ ok: false, title: "Risk information missing" }] } },
    { event: "done", data: { n_claims: 2 } },
  ]);
  assert.equal(doc.status, "done");
  assert.equal(doc.claims.length, 2);
  assert.equal(statusOf(doc.reviews[1]).label, "Off-label");
  assert.equal(statusOf(doc.reviews[2]).label, "Checking");
  assert.equal(doc.checks[0].title, "Risk information missing");
});

test("an error stays an error after done", () => {
  let doc = emptyDoc({ source: "live", id: "x", text: TEXT });
  doc = applyEvent(doc, "error", { message: "No indexed drug is named in the copy." });
  doc = applyEvent(doc, "done", {});
  assert.equal(doc.status, "error");
  assert.match(doc.error, /No indexed drug/);
});

test("trace steps read as sentences, including routing and fallbacks", () => {
  const steps = traceSteps({
    status: "needs_qualifier",
    violations: ["omitted_qualifier"],
    trace: [
      { step: "search_label", n_hits: 5, pinned_for_figures: 1, routed_to: ["Indications and Usage"], ms: 41 },
      { step: "judge", model: "groq/gpt-oss-20b", source: "live", ms: 2300, tokens: 2907,
        attempts: [{ model: "groq/gpt-oss-120b", skipped: "per-minute budget in use for 40s" }, { model: "groq/gpt-oss-20b" }] },
      { step: "guards", kept_quotes: 2, proposed_quotes: 3, ms: 0.4 },
    ],
  });
  assert.match(steps[0].detail, /always includes Indications and Usage/);
  assert.match(steps[1].detail, /gpt-oss-120b on Groq: per-minute budget in use/);
  assert.match(steps[1].detail, /gpt-oss-20b on Groq answered/);
  assert.equal(steps[1].meta, "2.3 s · 2,907 tokens");
  assert.match(steps[2].detail, /2 of 3 quotes found in the label; 1 dropped/);
  assert.equal(steps.at(-1).detail, "Needs a qualifier: omitted qualifier");
});
