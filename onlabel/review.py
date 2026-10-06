"""Review claims: retrieve label evidence, ask the judge, apply the guards.

`review_claim` checks one claim. `review_document` finds the claims in a piece of copy,
detects which label it is about, reviews each claim in reading order (reporting each one as
soon as it is done) and runs the document-level risk-information check.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from onlabel.agent.document import detect_labels, risk_information_check, split_claims
from onlabel.agent.evidence import BOXED_WARNING, DAILYMED_URL, present
from onlabel.agent.guards import check_verdict, checks_for
from onlabel.agent.judge import PROMPT_VERSION, judge_claim
from onlabel.data.corpus import label_name
from onlabel.llm.client import LLMClient
from onlabel.retrieval.encoder import OnnxEncoder
from onlabel.retrieval.index import LabelIndex
from onlabel.safety.injection import InjectionReport, scan

__all__ = ["DAILYMED_URL", "ClaimReview", "Reviewer"]

# The label sections that govern each kind of claim. Similarity search alone let an
# indication claim be judged without the Indications section (the Ozempic kidney claim was
# traced although the label limits it to adults with type 2 diabetes and CKD) and a safety
# claim without the contraindications, so these sections are always put in front of the judge.
SECTION_ROUTES = {
    "indication": ("34067-9",),
    "safety": ("34066-1", "34070-3", "43685-7"),
    "dosing": ("34068-7", "43678-2"),
    "comparative": ("34092-7",),
    "efficacy": ("34067-9", "34092-7"),
}
SECTION_NAMES = {
    "34067-9": "Indications and Usage", "34066-1": "Boxed Warning", "34070-3": "Contraindications",
    "43685-7": "Warnings and Precautions", "34068-7": "Dosage and Administration",
    "43678-2": "Dosage Forms and Strengths", "34092-7": "Clinical Studies",
}
ROUTED_PER_CLAIM = 2
MAX_EXCERPTS = 6


def gather(index: LabelIndex, claim: str, qvec, labels: list[str] | None, kind: str | None,
           k: int = 5) -> tuple[list, list]:
    """The excerpts the judge sees: governing sections first, then the similarity hits.

    Routing takes the best chunk of each governing section in route order, then fills with
    the next best of any of them. Taking the top two over all of them let the boxed warning
    and the thyroid precaution crowd out a one-chunk Contraindications section, so "do not
    use WEGOVY with a family history of MTC" was judged without the contraindication itself
    (benchmark dev split)."""
    hits = index.search(claim, qvec, k=k, labels=labels)
    codes = SECTION_ROUTES.get(kind or "", ())
    if not codes:
        return hits, []
    # Only the hits that always survive the cut count as present: a governing chunk sitting
    # at hit 5 would otherwise be skipped here and then cut.
    have = {h.chunk.chunk_id for h in hits[: MAX_EXCERPTS - ROUTED_PER_CLAIM]}
    ranked = {code: [h for h in index.search(claim, qvec, k=ROUTED_PER_CLAIM + 1, labels=labels, top_codes=[code])
                     if h.chunk.chunk_id not in have] for code in codes}
    routed = [ranked[code].pop(0) for code in codes if ranked[code]][:ROUTED_PER_CLAIM]
    taken = {h.chunk.chunk_id for h in routed}
    for h in sorted((h for hs in ranked.values() for h in hs), key=lambda h: -h.score):
        if len(routed) == ROUTED_PER_CLAIM:
            break
        if h.chunk.chunk_id not in taken:
            routed.append(h)
            taken.add(h.chunk.chunk_id)
    rest = [h for h in hits if h.chunk.chunk_id not in taken]
    return (routed + rest)[:MAX_EXCERPTS], routed


@dataclass
class ClaimReview:
    claim: str
    status: str
    model_verdict: str | None
    violations: list[str]
    reasoning: str
    evidence: list[dict]
    checks: list[dict]
    flags: list[str]
    retrieved: list[dict]
    model: str | None
    source: str
    prompt_version: str
    tokens: int
    latency_s: float
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Reviewer:
    # 5 excerpts: about 2.2K prompt tokens a claim; 6 cost a sixth more of a free minute budget.
    def __init__(self, index: LabelIndex, encoder: OnnxEncoder, llm: LLMClient, k: int = 5,
                 splitter: LLMClient | None = None,
                 prompt_guard: Callable[[str], float | None] | None = None) -> None:
        self.index, self.encoder, self.llm, self.k = index, encoder, llm, k
        self.splitter = splitter  # a cheaper chain for claim splitting; None means sentences
        self.prompt_guard = prompt_guard  # injection classifier; None means patterns only

    @property
    def labels_meta(self) -> dict[str, dict]:
        return self.index.meta.get("labels", {})

    def review_claim(self, claim: str, labels: list[str] | None = None, kind: str | None = None,
                     injection: InjectionReport | None = None) -> ClaimReview:
        """`injection` is the scan of the document the claim came from; a lone claim is scanned here."""
        t0 = time.perf_counter()
        trace: list[dict] = []
        if injection is None:
            injection = scan(claim, self.prompt_guard)

        t = time.perf_counter()
        qvec = self.encoder.encode_query(claim)
        hits, routed = gather(self.index, claim, qvec, labels, kind, k=self.k)
        routed_codes = SECTION_ROUTES.get(kind or "", ())
        trace.append({"step": "search_label", "labels": labels, "n_hits": len(hits),
                      "pinned_for_figures": sum(1 for h in hits if h.number_rank == 1),
                      "routed_to": [SECTION_NAMES[c] for c in routed_codes], "routed_added": len(routed),
                      "ms": round((time.perf_counter() - t) * 1000)})
        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        retrieved = [{"chunk_id": h.chunk.chunk_id, "section": h.chunk.section_path,
                      "score": round(h.score, 4), "dense_rank": h.dense_rank, "bm25_rank": h.bm25_rank,
                      "number_rank": h.number_rank} for h in hits]

        res = judge_claim(self.llm, claim, [h.chunk for h in hits])
        trace.append({"step": "judge", "model": res.model_key, "source": res.source,
                      "attempts": res.attempts, "tokens": res.prompt_tokens + res.completion_tokens,
                      "ms": round(res.latency_s * 1000)})

        if res.data is None:
            status, verdict, violations, flags = "needs_human_review", None, [], ["no_llm_available"]
            reasoning, evidence, checks = "No model was available to judge this claim.", [], checks_for(claim, None, None)
        else:
            t = time.perf_counter()
            guard = check_verdict(res.data, chunks, claim)
            trace.append({"step": "guards", "status": guard.status, "flags": guard.flags,
                          "kept_quotes": len(guard.evidence), "proposed_quotes": len(res.data.evidence),
                          "ms": round((time.perf_counter() - t) * 1000, 1)})
            status, verdict = guard.status, res.data.verdict
            violations, reasoning, flags = list(res.data.violations), res.data.reasoning, guard.flags
            evidence = [present(e, chunks[e.chunk_id], self.labels_meta.get(chunks[e.chunk_id].label_key))
                        for e in guard.evidence]
            checks = checks_for(claim, res.data, guard)

        if injection.flagged:
            # An approval the copy asked for is not an approval: nothing from it is traced.
            trace.append({"step": "injection", "findings": [f.why for f in injection.findings if f.flags],
                          "prompt_guard": injection.prompt_guard})
            if status == "supported":
                status = "needs_human_review"
            flags = [*flags, "injection_in_copy"]
            checks = [*checks, {"ok": False, "text": "The copy contains instructions aimed at the reviewer, "
                                                     "so no claim from it is traced."}]

        return ClaimReview(
            claim=claim, status=status, model_verdict=verdict, violations=violations,
            reasoning=reasoning, evidence=evidence, checks=checks, flags=flags, retrieved=retrieved,
            model=res.model_key, source=res.source, prompt_version=PROMPT_VERSION,
            tokens=res.prompt_tokens + res.completion_tokens,
            latency_s=round(time.perf_counter() - t0, 2), trace=trace,
        )

    def boxed_warning(self, label_key: str) -> list:
        return [c for c in self.index.chunks if c.label_key == label_key and c.top_code == BOXED_WARNING]

    def review_document(self, text: str, labels: list[str] | None, emit: Callable[[str, dict], None]) -> None:
        """Stream a document review through `emit(event, data)`: start, claims, claim (one per
        claim, in reading order), document, done."""
        t0 = time.perf_counter()
        ambiguous = False
        if not labels:
            labels, ambiguous = detect_labels(text, self.labels_meta)
        if not labels:
            emit("error", {"message": "No indexed drug is named in the copy. Pick the label to check against.",
                           "code": "no_label"})
            return
        injection = scan(text, self.prompt_guard)
        emit("start", {"labels": [{"key": k, **self.labels_meta.get(k, {}),
                                   "drug": label_name(self.labels_meta.get(k, {}).get("products", []), k)}
                                  for k in labels],
                       "ambiguous": ambiguous, "injection": injection.to_dict()})

        claims, split, omitted = split_claims(self.splitter, text)
        emit("claims", {"claims": [c.to_dict() for c in claims],
                        "split_by": claims[0].source if claims else "none",
                        "split_model": split.model_key if split else None,
                        "omitted": omitted})
        tokens = (split.prompt_tokens + split.completion_tokens) if split else 0
        for c in claims:
            review = self.review_claim(c.text, labels, kind=c.kind, injection=injection)
            tokens += review.tokens
            emit("claim", {"n": c.n, "review": review.to_dict()})

        checks = [injection_check(injection)] if injection.findings else []
        for key in labels:
            drug = label_name(self.labels_meta.get(key, {}).get("products", []), key)
            found = risk_information_check(text, key, drug, self.boxed_warning(key))
            if found:
                checks.append(found)
        emit("document", {"checks": checks})
        emit("done", {"seconds": round(time.perf_counter() - t0, 1), "tokens": tokens, "n_claims": len(claims)})


def injection_check(report: InjectionReport) -> dict:
    """The document check a reviewer reads first when the copy talks to the reviewer."""
    shown = [f for f in report.findings if f.flags] or report.findings
    reasons = "; ".join(dict.fromkeys(f.why for f in shown))
    excerpt = next((f.excerpt for f in shown if f.excerpt), "")
    detail = (f"Found in the copy: {reasons}. Every claim is still checked, but none is traced: an approval "
              "the copy asks for is not an approval." if report.flagged
              else f"Found in the copy: {reasons}. Nothing in it reads as an instruction.")
    return {"label": "injection", "drug": "", "ok": not report.flagged,
            "title": "Instructions aimed at the reviewer" if report.flagged else "Hidden characters removed",
            "detail": detail, "findings": [f.why for f in report.findings],
            "evidence": {"chunk_id": None, "section_path": "Found in the copy", "quote": excerpt} if excerpt else None}
