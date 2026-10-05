"""Deterministic checks on a judge's verdict. Pure functions: no I/O, no model.

The model proposes; these decide what is reported. The rules, in order:
  1. A citation counts only if its quote is found in the excerpt it names (`ground.locate`).
  2. "supported" with no surviving citation is not supported: it goes to a human.
  3. "supported" must carry every figure the claim states inside its own surviving
     quotes. The first skeleton run approved "14.9% at 68 weeks" on a quote of "-14.8",
     a real number from a different study: the quote check passed, the claim was wrong.
  4. "supported" that also lists violations contradicts itself: a human decides.
  5. A violation verdict with no surviving citation still flags the claim, but as a
     hand-off rather than an accusation the reviewer cannot check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from onlabel.agent.ground import locate
from onlabel.agent.verdict import JudgeOutput
from onlabel.data.chunk import Chunk

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def figures(text: str) -> set[str]:
    """Numbers in a text, normalised ("1,306" -> "1306", "15.0" -> "15"). Integers up to
    10 are left out: they are as often words in disguise ("type 2", "2 doses") as figures."""
    out = set()
    for raw in _NUMBER.findall(text):
        n = raw.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        if "." in n or int(n) > 10:
            out.add(n)
    return out


@dataclass
class CheckedEvidence:
    chunk_id: str
    quote: str
    match: str
    section_path: str
    set_id: str
    start: int  # offsets into the chunk's section text, for highlighting
    end: int


@dataclass
class GuardResult:
    status: str
    evidence: list[CheckedEvidence] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def check_verdict(out: JudgeOutput, chunks: dict[str, Chunk], claim: str = "") -> GuardResult:
    res = GuardResult(status=out.verdict)
    for ev in out.evidence:
        chunk = chunks.get(ev.chunk_id)
        if chunk is None:
            res.flags.append("cited_unknown_excerpt")
            continue
        haystack = f"{chunk.context}\n{chunk.text}" if chunk.context else chunk.text
        g = locate(haystack, ev.quote)
        if not g.ok:
            res.flags.append("quote_not_found_in_excerpt")
            continue
        offset = len(chunk.context) + 1 if chunk.context else 0
        start = chunk.start + max(0, g.start - offset)
        end = chunk.start + max(0, g.end - offset)
        res.evidence.append(CheckedEvidence(chunk.chunk_id, g.located or ev.quote, g.match,
                                            chunk.section_path, chunk.set_id, start, end))

    if out.verdict == "supported" and not res.evidence:
        res.status = "needs_human_review"
        res.flags.append("supported_without_grounded_quote")
    elif out.verdict == "supported":
        quoted = set().union(*(figures(e.quote) for e in res.evidence))
        missing = sorted(figures(claim) - quoted)
        if missing:
            res.status = "needs_human_review"
            res.flags.append(f"claim_figures_not_in_quotes:{','.join(missing)}")
        if out.violations:
            res.status = "needs_human_review"
            res.flags.append("supported_but_lists_violations")
    elif out.verdict in ("contradicted", "needs_qualifier", "off_label") and not res.evidence:
        res.status = "needs_human_review"
        res.flags.append("violation_without_grounded_quote")
    return res
