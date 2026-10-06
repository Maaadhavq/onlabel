"""Deterministic checks on a judge's verdict. Pure functions: no I/O, no model.

The model proposes; these decide what is reported. The rules, in order:
  1. A citation counts only if its quote is found in the label text the judge was shown
     (`ground.locate`). A quote found word for word in an excerpt other than the one it
     names is moved there: two labels can carry the same sentence (Ozempic and Rybelsus),
     and models mix up excerpt ids.
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
# Small whole numbers count only with a unit or an age: "type 2" and "MEN 2" are names, but
# "as young as 8" and "for 4 weeks" are figures. Skipping every integer up to 10 let a claim
# about children "as young as 8" pass on a quote that says "12 years and older".
_SMALL_FIGURE = re.compile(
    r"(?<![\d.,])(\d{1,2})\s*(?:%|mg\b|mcg\b|kg\b|years?\b|yrs?\b|months?\b|weeks?\b|days?\b|hours?\b"
    r"|times?\b|and (?:older|over|up)\b)"
    r"|\b(?:aged?|ages|as young as|older than|younger than|under|over)\s+(\d{1,2})\b(?![.,]\d)",
    re.IGNORECASE)


def _norm(raw: str) -> str:
    n = raw.replace(",", "")
    return n.rstrip("0").rstrip(".") if "." in n else str(int(n))


def figures(text: str) -> set[str]:
    """The figures a claim states, normalised ("1,306" -> "1306", "15.0" -> "15"). Whole
    numbers up to 10 count only with a unit or an age attached (see _SMALL_FIGURE)."""
    out = {n for n in map(_norm, _NUMBER.findall(text)) if "." in n or int(n) > 10}
    out |= {str(int(m.group(1) or m.group(2))) for m in _SMALL_FIGURE.finditer(text)}
    return out


def numbers(text: str) -> set[str]:
    """Every number in a quote. A quote vouches for any number it contains: a table cell says
    "-3" with the "%" in its column header, while the claim says "3%"."""
    return set(map(_norm, _NUMBER.findall(text)))


@dataclass
class CheckedEvidence:
    chunk_id: str
    quote: str
    match: str
    section_path: str
    set_id: str
    start: int  # offsets into the chunk's section text, for highlighting
    end: int
    parts: list[tuple[int, int]] = field(default_factory=list)  # the spans actually quoted, same offsets


@dataclass
class GuardResult:
    status: str
    evidence: list[CheckedEvidence] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _haystack(chunk: Chunk) -> tuple[str, int]:
    """What a quote may come from (section title, table caption and header rows, the excerpt
    itself) and where the excerpt's own text starts in it. The judge sees all three."""
    head = "\n".join(p for p in (chunk.section_path, chunk.context) if p)
    return f"{head}\n{chunk.text}", len(head) + 1


def _find(quote: str, cited: Chunk | None, chunks: dict[str, Chunk]):
    """Where a quote is: in the excerpt it cites, or else word for word (never fuzzily) in
    another excerpt the judge was shown. Returns (chunk, grounding, haystack, text_at)."""
    if cited is not None:
        haystack, text_at = _haystack(cited)
        g = locate(haystack, quote)
        if g.ok:
            return cited, g, haystack, text_at
    for other in chunks.values():
        if other is cited:
            continue
        haystack, text_at = _haystack(other)
        g = locate(haystack, quote)
        if g.ok and g.match != "fuzzy":
            return other, g, haystack, text_at
    return None


def check_verdict(out: JudgeOutput, chunks: dict[str, Chunk], claim: str = "") -> GuardResult:
    res = GuardResult(status=out.verdict)
    # Figures a quote can vouch for: the label text it actually quotes (never a middle it
    # skipped), plus its table's caption and header rows (a row of numbers means nothing
    # without "Week 68" above it). Never the section title: titles carry "14.2" and
    # "12 Years" and would wave a wrong figure through.
    vouched: set[str] = set()
    for ev in out.evidence:
        if not ev.quote.strip():
            continue  # an empty quote is no citation (Gemma sends them)
        cited = chunks.get(ev.chunk_id)
        found = _find(ev.quote, cited, chunks)
        if found is None:
            res.flags.append("cited_unknown_excerpt" if cited is None else "quote_not_found_in_excerpt")
            continue
        chunk, g, haystack, text_at = found
        if chunk is not cited:
            res.flags.append("quote_reattributed")
        start = chunk.start + max(0, g.start - text_at)  # a title or header quote highlights
        end = chunk.start + max(0, g.end - text_at)  # the start of the excerpt
        located = g.located or ev.quote
        parts = [(chunk.start + max(0, s - text_at), chunk.start + max(0, e - text_at)) for s, e in g.parts]
        res.evidence.append(CheckedEvidence(chunk.chunk_id, located, g.match,
                                            chunk.section_path, chunk.set_id, start, end, parts))
        quoted = " ".join(haystack[s:e] for s, e in g.parts) if g.parts else located
        vouched |= numbers(quoted) | numbers(chunk.context)

    if out.verdict == "supported" and not res.evidence:
        res.status = "needs_human_review"
        res.flags.append("supported_without_grounded_quote")
    elif out.verdict == "supported":
        quoted = vouched
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


def checks_for(claim: str, out: JudgeOutput | None, res: GuardResult | None) -> list[dict]:
    """What the guards found, in sentences a reviewer can read. `ok` False marks a catch."""
    if out is None or res is None:
        return [{"ok": False, "text": "No model was available, so a reviewer decides."}]
    checks: list[dict] = []
    proposed, kept = sum(1 for e in out.evidence if e.quote.strip()), len(res.evidence)
    if proposed:
        checks.append({"ok": kept == proposed,
                       "text": f"{kept} of {proposed} quotes found word for word in the label."})
        if kept < proposed:
            dropped = proposed - kept
            checks.append({"ok": False, "text": f"{dropped} quote{'s' if dropped > 1 else ''} dropped: "
                                                "the wording is not in the label text."})
    elif out.verdict == "unsupported":
        checks.append({"ok": True, "text": "No label text supports the claim, so no quote was expected."})
    else:
        checks.append({"ok": False, "text": "The model gave no quotes."})

    claimed = figures(claim)
    missing = next((f.split(":", 1)[1] for f in res.flags if f.startswith("claim_figures_not_in_quotes:")), None)
    if missing:
        checks.append({"ok": False, "text": f"Figures in the claim missing from every quote: {missing.replace(',', ', ')}. "
                                            "A reviewer decides."})
    elif claimed and res.status == "supported":
        checks.append({"ok": True, "text": f"Figures {', '.join(sorted(claimed))} appear in the quoted label text."})
    elif not claimed:
        checks.append({"ok": True, "text": "No figures in the claim to check."})
    if "supported_but_lists_violations" in res.flags:
        checks.append({"ok": False, "text": "The model said traced and also listed violations, so a reviewer decides."})
    if "violation_without_grounded_quote" in res.flags:
        checks.append({"ok": False, "text": "The model flagged a problem without a quote found in the label, "
                                            "so a reviewer decides."})
    if "cited_unknown_excerpt" in res.flags:
        checks.append({"ok": False, "text": "The model cited an excerpt it was not shown. That citation was dropped."})
    moved = res.flags.count("quote_reattributed")
    if moved:
        what = "1 quote named the wrong excerpt; it was" if moved == 1 else f"{moved} quotes named the wrong excerpt; they were"
        checks.append({"ok": True, "text": f"{what} found word for word in another excerpt the model was shown, "
                                           "and the evidence shows where."})
    return checks
