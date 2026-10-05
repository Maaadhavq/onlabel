"""The grounding gate: a model may cite the label only if it can quote it.

Ported from tieout's `ingest/ground.py` (PDF pages there, label chunks here). No model
takes part in this step. Match ladder, strictest first:

    exact       the quote appears verbatim in the evidence text
    normalized  it appears after folding whitespace, dashes, quotes, ligatures and the
                "- " bullet markers this project's SPL renderer writes
    elided      the quote was shortened with "..." and every fragment appears, in order,
                after folding (models do this with long label sentences; gpt-oss-120b's
                first pediatric verdict was rejected for it). Never fuzzy.
    fuzzy       >= FUZZY_MIN similarity over a same-length window (only for quotes with
                no digits: "14.9%" and "19.4%" are 80% similar and mean different things)
    failed      -> the citation is rejected
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

FUZZY_MIN = 0.90
MIN_QUOTE_CHARS = 12

_FOLD = {
    "­": "",  # soft hyphen
    "ﬁ": "fi", "ﬂ": "fl",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
    "•": " ", "|": " ",  # bullets and table cell separators carry no meaning in a quote
}
_BULLET = re.compile(r"(?m)^[ \t]*- ")
_DIGIT = re.compile(r"\d")
_ELLIPSIS = re.compile(r"\s*(?:\.{3}|…)\s*")
MIN_FRAGMENT_CHARS = 4
# An elision can drop a "not". Callers show the located span (elided middle included), never
# the model's shortened text, and a span this long is no longer a quotation.
MAX_ELIDED_SPAN = 800


@dataclass
class Grounding:
    match: str  # "exact" | "normalized" | "fuzzy" | "failed"
    start: int | None = None
    end: int | None = None
    located: str | None = None

    @property
    def ok(self) -> bool:
        return self.match != "failed"


def _fold_index(text: str) -> tuple[str, list[int]]:
    """Folded, whitespace-collapsed, lowercased text plus folded -> raw offsets."""
    skip: set[int] = set()
    for m in _BULLET.finditer(text):
        skip.update(range(m.end() - 2, m.end()))  # the "- " itself
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if i in skip:
            continue
        repl = _FOLD.get(ch, ch)
        if not repl:
            continue
        if repl.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        for c in repl.lower():
            out.append(c)
            idx.append(i)
        prev_space = False
    return "".join(out), idx


def locate(text: str, quote: str) -> Grounding:
    quote = (quote or "").strip().strip('"').strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return Grounding("failed")

    pos = text.find(quote)
    if pos >= 0:
        return Grounding("exact", pos, pos + len(quote), quote)

    folded, back = _fold_index(text)
    nquote = _fold_index(quote)[0].strip()
    if not nquote or not back:
        return Grounding("failed")

    def span(p: int) -> tuple[int, int]:
        return back[p], back[min(p + len(nquote), len(back)) - 1] + 1

    pos = folded.find(nquote)
    if pos >= 0:
        s, e = span(pos)
        return Grounding("normalized", s, e, text[s:e])

    if _ELLIPSIS.search(quote):
        return _elided(text, quote, folded, back)

    if _DIGIT.search(nquote) or len(nquote) < MIN_QUOTE_CHARS:
        return Grounding("failed")
    best, best_pos = 0.0, -1
    matcher = difflib.SequenceMatcher(autojunk=False, b=nquote)
    for i in range(0, max(1, len(folded) - len(nquote) + 1), max(1, len(nquote) // 8)):
        matcher.set_seq1(folded[i : i + len(nquote)])
        if matcher.real_quick_ratio() < best or matcher.quick_ratio() < best:
            continue
        r = matcher.ratio()
        if r > best:
            best, best_pos = r, i
    if best >= FUZZY_MIN:
        s, e = span(best_pos)
        return Grounding("fuzzy", s, e, text[s:e])
    return Grounding("failed")


def _elided(text: str, quote: str, folded: str, back: list[int]) -> Grounding:
    """Every fragment of an elided quote must appear in order; no fuzzy matching."""
    fragments = [_fold_index(f)[0].strip() for f in _ELLIPSIS.split(quote)]
    fragments = [f for f in fragments if f]
    if not fragments or any(len(f) < MIN_FRAGMENT_CHARS for f in fragments):
        return Grounding("failed")
    if sum(len(f) for f in fragments) < MIN_QUOTE_CHARS:
        return Grounding("failed")
    pos, first = 0, None
    for frag in fragments:
        hit = folded.find(frag, pos)
        if hit < 0:
            return Grounding("failed")
        first = hit if first is None else first
        pos = hit + len(frag)
    s, e = back[first], back[pos - 1] + 1
    if e - s > MAX_ELIDED_SPAN:
        return Grounding("failed")
    return Grounding("elided", s, e, text[s:e])
