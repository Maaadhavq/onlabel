"""Review one claim: retrieve label evidence, ask the judge, apply the guards.

This is the walking skeleton's whole pipeline. The agent (claim decomposition, tool plan,
replanning, verifier cascade) replaces the middle of `review_claim` in Phase 4; the
retrieve -> judge -> guard contract stays.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from onlabel.agent.guards import check_verdict
from onlabel.agent.judge import PROMPT_VERSION, judge_claim
from onlabel.llm.client import LLMClient
from onlabel.retrieval.encoder import OnnxEncoder
from onlabel.retrieval.index import LabelIndex

DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"


@dataclass
class ClaimReview:
    claim: str
    status: str
    model_verdict: str | None
    violations: list[str]
    reasoning: str
    evidence: list[dict]
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
    def __init__(self, index: LabelIndex, encoder: OnnxEncoder, llm: LLMClient, k: int = 6) -> None:
        self.index, self.encoder, self.llm, self.k = index, encoder, llm, k

    def review_claim(self, claim: str, labels: list[str] | None = None) -> ClaimReview:
        t0 = time.perf_counter()
        trace: list[dict] = []

        t = time.perf_counter()
        hits = self.index.search(claim, self.encoder.encode_query(claim), k=self.k, labels=labels)
        trace.append({"step": "search_label", "args": {"labels": labels, "k": self.k},
                      "n_hits": len(hits), "ms": round((time.perf_counter() - t) * 1000)})
        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        retrieved = [{"chunk_id": h.chunk.chunk_id, "section": h.chunk.section_path,
                      "score": round(h.score, 4), "dense_rank": h.dense_rank, "bm25_rank": h.bm25_rank}
                     for h in hits]

        res = judge_claim(self.llm, claim, [h.chunk for h in hits])
        trace.append({"step": "judge", "model": res.model_key, "source": res.source,
                      "attempts": res.attempts, "tokens": res.prompt_tokens + res.completion_tokens,
                      "ms": round(res.latency_s * 1000)})

        if res.data is None:
            status, verdict, violations, reasoning, evidence, flags = (
                "needs_human_review", None, [], "No model was available to judge this claim.", [], ["no_llm_available"])
        else:
            guard = check_verdict(res.data, chunks, claim)
            trace.append({"step": "guards", "status": guard.status, "flags": guard.flags,
                          "kept_quotes": len(guard.evidence), "proposed_quotes": len(res.data.evidence)})
            status, verdict = guard.status, res.data.verdict
            violations, reasoning, flags = list(res.data.violations), res.data.reasoning, guard.flags
            evidence = [{**asdict(e), "url": DAILYMED_URL.format(set_id=e.set_id)} for e in guard.evidence]

        return ClaimReview(
            claim=claim, status=status, model_verdict=verdict, violations=violations,
            reasoning=reasoning, evidence=evidence, flags=flags, retrieved=retrieved,
            model=res.model_key, source=res.source, prompt_version=PROMPT_VERSION,
            tokens=res.prompt_tokens + res.completion_tokens,
            latency_s=round(time.perf_counter() - t0, 2), trace=trace,
        )
