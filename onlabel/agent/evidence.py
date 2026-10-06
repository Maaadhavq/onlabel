"""Shape a grounded quote for the reviewer: the label text around it, and its kind.

A quote alone is hard to judge, so the panel shows it in place: up to a sentence of label
text on either side, a boxed warning drawn as the label's black box, and a table quote as
the table itself with the quoted rows marked.
"""

from __future__ import annotations

from onlabel.agent.guards import CheckedEvidence
from onlabel.data.chunk import Chunk

BOXED_WARNING = "34066-1"
CONTEXT_CHARS = 240
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"


def _cells(line: str) -> list[str]:
    """Split a rendered row. Whitespace collapsing turned empty cells into "| | |", so split
    on the bar itself and trim; a leading bar means an empty first cell."""
    cells = [c.strip() for c in line.split("|")]
    if cells and cells[0].startswith("- "):
        cells[0] = cells[0][2:]
    return cells


def _is_row(line: str) -> bool:
    return line.count("|") >= 1 and (" | " in line or line.startswith("| ") or line.endswith(" |"))


def _table(chunk: Chunk, q_start: int, q_end: int, quoted: list[tuple[int, int]]) -> dict | None:
    """The chunk's table with the rows the quote covers marked; None if not a table quote.
    `quoted` are the spans the model actually quoted: a caption plus one row marks that row,
    never the rows it skipped."""
    lines, pos = [], 0
    for ln in chunk.text.split("\n"):
        lines.append((pos, pos + len(ln), ln))
        pos += len(ln) + 1
    body = [(s, e, ln) for s, e, ln in lines if _is_row(ln)]
    if not body or not any(s < q_end and e > q_start for s, e, _ in body):
        return None
    ctx = [ln for ln in chunk.context.split("\n") if ln] if chunk.context else []
    header = [ln for ln in ctx if _is_row(ln)]
    caption = next((ln.lstrip("- ") for ln in ctx if not _is_row(ln)), "")
    if not chunk.context:  # the chunk starts at the table's top: its first rows are the header
        n_header = 2 if len(body) > 4 else 1
        header, body = [ln for _, _, ln in body[:n_header]], body[n_header:]
        caption = next((ln.lstrip("- ") for _, _, ln in lines if ln.lower().lstrip("- ").startswith("table")), caption)
    return {
        "caption": caption,
        "header": [_cells(h) for h in header],
        "rows": [_cells(ln) for _, _, ln in body],
        "highlight": [i for i, (s, e, _) in enumerate(body) if any(s < qe and e > qs for qs, qe in quoted)],
    }


def _clip_before(text: str) -> str:
    if len(text) <= CONTEXT_CHARS:
        return text
    cut = text[-CONTEXT_CHARS:]
    space = cut.find(" ")
    return "…" + (cut[space + 1 :] if space >= 0 else cut)


def _clip_after(text: str) -> str:
    if len(text) <= CONTEXT_CHARS:
        return text
    cut = text[:CONTEXT_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut) + "…"


def present(ev: CheckedEvidence, chunk: Chunk, label_meta: dict | None = None) -> dict:
    meta = label_meta or {}
    q_start = max(0, ev.start - chunk.start)
    q_end = min(len(chunk.text), max(q_start, ev.end - chunk.start))
    in_text = q_end > q_start and chunk.text[q_start:q_end].strip() != ""
    out = {
        "chunk_id": ev.chunk_id,
        "quote": ev.quote,
        "match": ev.match,
        "section_path": ev.section_path,
        "drug": chunk.drug,
        "label_version": chunk.version,
        "effective_time": meta.get("effective_time"),
        "url": DAILYMED_URL.format(set_id=ev.set_id),
        "kind": "boxed" if chunk.top_code == BOXED_WARNING else "text",
        "before": _clip_before(chunk.text[:q_start]) if in_text else "",
        "after": _clip_after(chunk.text[q_end:]) if in_text else "",
        "table": None,
    }
    if in_text:
        quoted = [(max(0, s - chunk.start), min(len(chunk.text), e - chunk.start)) for s, e in ev.parts]
        table = _table(chunk, q_start, q_end, [p for p in quoted if p[1] > p[0]] or [(q_start, q_end)])
        if table is not None:
            out["kind"], out["table"] = "table", table
    return out
