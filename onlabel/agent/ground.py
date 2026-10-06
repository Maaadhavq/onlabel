"""The grounding gate: a model may cite the label only if it can quote it.

Ported from tieout's `ingest/ground.py` (PDF pages there, label chunks here). No model
takes part in this step. Match ladder, strictest first:

    exact       the quote appears verbatim in the evidence text
    normalized  it appears after folding whitespace, dashes, quotes, ligatures, bullet
                markers (at a line start or flattened into the line), superscript and
                footnote marks and "[see ...]" cross-references
    elided      the quote was shortened with "..." and every fragment appears, in order,
                after folding (models do this with long label sentences; gpt-oss-120b's
                first pediatric verdict was rejected for it). Never fuzzy.
    stitched    parts of the quote appear in order with only whole lines skipped between
                them: a list's lead-in with one of its items, a table caption with the row
                a claim needs. Each part matches after folding; never fuzzy.
    fuzzy       >= FUZZY_MIN similarity over a same-length window (only for quotes with
                no digits: "14.9%" and "19.4%" are 80% similar and mean different things)
    failed      -> the citation is rejected

Every match records the spans of the label text the model actually quoted (`parts`), so
figures in a skipped middle never count as quoted.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

FUZZY_MIN = 0.90
MIN_QUOTE_CHARS = 12

_FOLD = {
    "­": "",  # soft hyphen
    "ﬁ": "fi", "ﬂ": "fl",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",  # no-break, thin and narrow no-break spaces
    "•": " ", "|": " ",  # bullets and table cell separators carry no meaning in a quote
}
_BULLET = re.compile(r"(?m)^[ \t]*- ")
# A marker or dash standing between spaces. Models flatten a list into one line ("patients
# with: - A personal or family history of MTC"), so the marker is no longer at a line start;
# 23 of 89 quotes the guards rejected on the benchmark failed only on this.
_SPACED_DASH = re.compile("(?:(?<=\\s)|^)[-\u2010\u2011\u2012\u2013\u2014\u2212](?= )")
# The renderer writes superscripts as "^": "MOUNJARO^®", "(LSMean)^3", "0.9)^*,2". Models
# drop them. "m^2" folds to "m" on both sides, which is harmless.
_CARET_MARK = re.compile("\\^(?=[\u00ae\u2122])")
_FOOTNOTE = re.compile("\\^[0-9a-z*,\u2020\u2021\u00a7]{1,4}(?![0-9A-Za-z])")
# Cross-references carry no claim: "(MEN 2) [see Warnings and Precautions (5.1)]."
_SEE_REF = re.compile(r"\s*\[see [^\]]*\]", re.IGNORECASE)
_DIGIT = re.compile(r"\d")
_ELLIPSIS = re.compile(r"\s*(?:\.{3}|…)\s*")
MIN_FRAGMENT_CHARS = 4
# An elision can drop a "not". Callers show the located span (elided middle included), never
# the model's shortened text, and a span this long is no longer a quotation.
MAX_ELIDED_SPAN = 800
# A stitched quote may skip a few table rows and footnotes between a caption and its row.
MIN_STITCH_PART = 12
MAX_STITCH_PARTS = 4
MAX_STITCHED_SPAN = 1600
_LINE_TAIL = re.compile(r"[\s.,;:)\]]*")  # what may follow a part's end on its line
_LINE_HEAD = re.compile("[\\s|\u2022\\-\u2010\u2011\u2012\u2013\u2014\u2212]*")  # what may precede a part's start


@dataclass
class Grounding:
    match: str  # "exact" | "normalized" | "elided" | "stitched" | "fuzzy" | "failed"
    start: int | None = None
    end: int | None = None
    located: str | None = None
    parts: list[tuple[int, int]] = field(default_factory=list)  # the spans actually quoted

    @property
    def ok(self) -> bool:
        return self.match != "failed"


def _skipped(text: str) -> set[int]:
    skip: set[int] = set()
    for m in _BULLET.finditer(text):
        skip.update(range(m.end() - 2, m.end()))  # the "- " itself
    for rx in (_SPACED_DASH, _CARET_MARK, _FOOTNOTE, _SEE_REF):
        for m in rx.finditer(text):
            skip.update(range(m.start(), m.end()))
    return skip


def _fold_index(text: str) -> tuple[str, list[int]]:
    """Folded, whitespace-collapsed, lowercased text plus folded -> raw offsets."""
    skip = _skipped(text)
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
        return Grounding("exact", pos, pos + len(quote), quote, [(pos, pos + len(quote))])

    folded, back = _fold_index(text)
    nquote = _fold_index(quote)[0].strip()
    if not nquote or not back:
        return Grounding("failed")

    def span(p: int, n: int) -> tuple[int, int]:
        return back[p], back[min(p + n, len(back)) - 1] + 1

    pos = folded.find(nquote)
    if pos >= 0:
        s, e = span(pos, len(nquote))
        return Grounding("normalized", s, e, text[s:e], [(s, e)])

    if _ELLIPSIS.search(quote):
        return _elided(text, quote, folded, back)

    stitched = _stitched(text, nquote, folded, back)
    if stitched.ok:
        return stitched

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
        s, e = span(best_pos, len(nquote))
        return Grounding("fuzzy", s, e, text[s:e], [(s, e)])
    return Grounding("failed")


def _elided(text: str, quote: str, folded: str, back: list[int]) -> Grounding:
    """Every fragment of an elided quote must appear in order; no fuzzy matching."""
    fragments = [_fold_index(f)[0].strip() for f in _ELLIPSIS.split(quote)]
    fragments = [f for f in fragments if f]
    if not fragments or any(len(f) < MIN_FRAGMENT_CHARS for f in fragments):
        return Grounding("failed")
    if sum(len(f) for f in fragments) < MIN_QUOTE_CHARS:
        return Grounding("failed")
    pos, parts = 0, []
    for frag in fragments:
        hit = folded.find(frag, pos)
        if hit < 0:
            return Grounding("failed")
        parts.append((back[hit], back[hit + len(frag) - 1] + 1))
        pos = hit + len(frag)
    s, e = parts[0][0], parts[-1][1]
    if e - s > MAX_ELIDED_SPAN:
        return Grounding("failed")
    return Grounding("elided", s, e, text[s:e], parts)


def _longest_prefix_at(folded: str, rest: str, pos: int) -> tuple[int, int]:
    """Length and position of the longest prefix of `rest` found at or after `pos`.
    If a prefix is found, so is every shorter one, so the lengths found form a range."""
    lo, hi, best = 1, len(rest), (0, -1)
    while lo <= hi:
        mid = (lo + hi) // 2
        hit = folded.find(rest[:mid], pos)
        if hit >= 0:
            best, lo = (mid, hit), mid + 1
        else:
            hi = mid - 1
    return best


def _ends_a_line(text: str, end: int) -> bool:
    nl = text.find("\n", end)
    tail = text[end:] if nl < 0 else text[end:nl]
    return nl >= 0 and bool(_LINE_TAIL.fullmatch(_SEE_REF.sub("", _FOOTNOTE.sub("", tail))))


def _starts_a_line(text: str, start: int) -> bool:
    return bool(_LINE_HEAD.fullmatch(text[text.rfind("\n", 0, start) + 1 : start]))


def _stitched(text: str, nquote: str, folded: str, back: list[int]) -> Grounding:
    """Parts of the quote in order, each found word for word, with only whole lines between.

    Every part but the last must end where a line ends, and every part but the first must
    start where a line starts, so nothing is dropped from the middle of a line. Greedy
    matching alone overshoots: in "indicated: - to reduce the risk of MACE ... - to reduce
    excess body weight", the lead-in's longest match runs on into the wrong item."""
    parts: list[tuple[int, int]] = []  # folded offsets
    pos, rest = 0, nquote
    while rest:
        if len(parts) == MAX_STITCH_PARTS:
            return Grounding("failed")
        longest, _ = _longest_prefix_at(folded, rest, pos)
        found = None
        for n in range(longest, MIN_STITCH_PART - 1, -1):
            frag = rest[:n].rstrip()
            if len(frag) < MIN_STITCH_PART:
                break
            last = n >= len(rest)
            hit = folded.find(frag, pos)
            while hit >= 0 and found is None:
                s, e = back[hit], back[hit + len(frag) - 1] + 1
                if (not parts or _starts_a_line(text, s)) and (last or _ends_a_line(text, e)):
                    found = (hit, len(frag), n)
                hit = folded.find(frag, hit + 1)
            if found:
                break
        if found is None:
            return Grounding("failed")
        hit, length, n = found
        parts.append((hit, hit + length))
        pos, rest = hit + length, rest[n:].lstrip()
    if len(parts) < 2:
        return Grounding("failed")  # one part would have been a normalized match
    raw = [(back[a], back[b - 1] + 1) for a, b in parts]
    s, e = raw[0][0], raw[-1][1]
    if e - s > MAX_STITCHED_SPAN:
        return Grounding("failed")
    return Grounding("stitched", s, e, text[s:e], raw)
