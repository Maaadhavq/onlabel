import { test } from "node:test";
import assert from "node:assert/strict";
import { applyEvent, buildAudit, emptyDoc, nextWithStatus, replay, segments, shortSection, statusOf, traceSteps, wordDiff } from "./review.js";

test("section captions are short and readable", () => {
  assert.equal(shortSection("1 INDICATIONS AND USAGE"), "1 Indications and Usage");
  assert.equal(shortSection("8 USE IN SPECIFIC POPULATIONS > 8.4 Pediatric Use"), "8.4 Pediatric Use");
  const long = shortSection("14 CLINICAL STUDIES > 14.2 Weight Reduction and Long-term Maintenance Studies in Adults with Obesity or Overweight");
  assert.ok(long.length <= 64 && long.endsWith("…") && long.startsWith("14.2 Weight Reduction"));
});

test("word diff marks what a rewrite removed and added", () => {
  const d = wordDiff("Wegovy is approved for children as young as 8.", "Wegovy is approved for patients aged 12 years and older.");
  assert.deepEqual(d.map((p) => p.type), ["same", "del", "add"]);
  assert.equal(d[0].text, "Wegovy is approved for");
  assert.equal(d[1].text, "children as young as 8.");
});

test("legend jumps cycle through claims with that verdict", () => {
  const doc = { claims: [{ n: 1 }, { n: 2 }, { n: 3 }], reviews: { 1: { status: "off_label" }, 2: { status: "supported" }, 3: { status: "off_label" } } };
  assert.equal(nextWithStatus(doc, "Off-label", 1), 3);
  assert.equal(nextWithStatus(doc, "Off-label", 3), 1);
  assert.equal(nextWithStatus(doc, "Traced to label", 1), 2);
});

test("the audit file carries verdicts, quotes and reviewer decisions", () => {
  const doc = replay({ source: "sample", id: "s", title: "T", text: "Claim one here.", audience: "hcp" }, [
    { event: "start", data: { labels: [{ key: "w", products: ["W"], set_id: "x", version: 1 }] } },
    { event: "claims", data: { claims: [{ n: 1, text: "Claim one here.", start: 0, end: 15 }] } },
    { event: "claim", data: { n: 1, review: { status: "contradicted", violations: ["minimized_risk"], evidence: [{ section_path: "5.1 X", quote: "q", match: "exact", url: "u" }], checks: [] } } },
  ]);
  const audit = buildAudit(doc, { 1: { choice: "agree", note: "fine" } });
  assert.equal(audit.claims[0].verdict, "Conflicts with label");
  assert.equal(audit.claims[0].evidence[0].quote, "q");
  assert.deepEqual(audit.claims[0].reviewer, { choice: "agree", note: "fine" });
  assert.equal(audit.labels[0].set_id, "x");
});

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

test("label text reads cleanly: trademark marks and blank lines", async () => {
  const { tidy } = await import("./review.js");
  assert.equal(tidy("MOUNJARO^® is indicated:\n\n- as an adjunct"), "MOUNJARO® is indicated:\n- as an adjunct");
  assert.equal(tidy("eGFR 30 mL/min/1.73 m^2"), "eGFR 30 mL/min/1.73 m^2");
  assert.equal(tidy(undefined), "");
});

test("labels are named by their brands, device presentations left out", async () => {
  const { labelName } = await import("./review.js");
  assert.equal(labelName({ key: "mounjaro", products: ["MOUNJARO", "MOUNJARO KWIKPEN"] }), "MOUNJARO");
  assert.equal(labelName({ key: "rybelsus", products: ["OZEMPIC", "RYBELSUS"] }), "RYBELSUS and OZEMPIC");
  assert.equal(labelName({ key: "zepbound", drug: "ZEPBOUND", products: ["ZEPBOUND", "ZEPBOUND KWIKPEN"] }), "ZEPBOUND");
  assert.equal(labelName({ key: "lantus" }), "LANTUS");
});

test("claims the splitter left out are carried to the page and the audit", async () => {
  const { applyEvent, buildAudit, emptyDoc } = await import("./review.js");
  let doc = emptyDoc({ source: "live", id: "x", title: "t", text: "copy", audience: "consumer" });
  doc = applyEvent(doc, "claims", { claims: [{ n: 1, text: "a", start: 0, end: 1 }], split_by: "model", omitted: 3 });
  assert.equal(doc.omitted, 3);
  assert.equal(buildAudit(doc).claims_not_checked, 3);
});
