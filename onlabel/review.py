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
from onlabel.llm.client import LLMClient
from onlabel.retrieval.encoder import OnnxEncoder
from onlabel.retrieval.index import LabelIndex

__all__ = ["DAILYMED_URL", "ClaimReview", "Reviewer"]


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
    def __init__(self, index: LabelIndex, encoder: OnnxEncoder, llm: LLMClient, k: int = 6,
                 splitter: LLMClient | None = None) -> None:
        self.index, self.encoder, self.llm, self.k = index, encoder, llm, k
        self.splitter = splitter  # a cheaper chain for claim splitting; None means sentences

    @property
    def labels_meta(self) -> dict[str, dict]:
        return self.index.meta.get("labels", {})

    def review_claim(self, claim: str, labels: list[str] | None = None) -> ClaimReview:
        t0 = time.perf_counter()
        trace: list[dict] = []

        t = time.perf_counter()
        hits = self.index.search(claim, self.encoder.encode_query(claim), k=self.k, labels=labels)
        trace.append({"step": "search_label", "labels": labels, "n_hits": len(hits),
                      "pinned_for_figures": sum(1 for h in hits if h.number_rank == 1),
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
        emit("start", {"labels": [{"key": k, **self.labels_meta.get(k, {})} for k in labels],
                       "ambiguous": ambiguous})

        claims, split = split_claims(self.splitter, text)
        emit("claims", {"claims": [c.to_dict() for c in claims],
                        "split_by": claims[0].source if claims else "none",
                        "split_model": split.model_key if split else None})
        tokens = (split.prompt_tokens + split.completion_tokens) if split else 0
        for c in claims:
            review = self.review_claim(c.text, labels)
            tokens += review.tokens
            emit("claim", {"n": c.n, "review": review.to_dict()})

        checks = []
        for key in labels:
            meta = self.labels_meta.get(key, {})
            drug = (meta.get("products") or [key.upper()])[0]
            found = risk_information_check(text, key, drug, self.boxed_warning(key))
            if found:
                checks.append(found)
        emit("document", {"checks": checks})
        emit("done", {"seconds": round(time.perf_counter() - t0, 1), "tokens": tokens, "n_claims": len(claims)})
