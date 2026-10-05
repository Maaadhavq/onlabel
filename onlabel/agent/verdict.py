"""What a reviewer (model or rules) can say about one claim.

The verdict and violation names follow the language of FDA OPDP untitled letters, so the
holdout built from those letters can be scored without a translation table.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["supported", "needs_qualifier", "unsupported", "contradicted", "off_label"]
Violation = Literal[
    "overstated_efficacy",
    "unsubstantiated_superiority",
    "broadened_indication",
    "omitted_qualifier",
    "minimized_risk",
    "missing_risk_information",
    "unsupported_absolute_claim",
]
# What the pipeline reports after the guards: the model's verdict, or a hand-off.
Status = Literal[
    "supported", "needs_qualifier", "unsupported", "contradicted", "off_label", "needs_human_review"
]


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str = Field(description="id of the label excerpt the quote comes from, e.g. wegovy:v19:3:0")
    quote: str = Field(description="exact sentence or table row copied from that excerpt")


class JudgeOutput(BaseModel):
    """The LLM judge's answer. `reasoning` comes first so the verdict is conditioned on it."""

    model_config = ConfigDict(extra="forbid")
    reasoning: str = Field(description="at most three sentences comparing the claim with the excerpts")
    verdict: Verdict
    violations: list[Violation]
    evidence: list[EvidenceQuote]
