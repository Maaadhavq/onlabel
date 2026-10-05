"""Split label sections into retrieval chunks that remember where they came from.

Every chunk keeps character offsets into its section's text and into the whole label
(`doc_start`/`doc_end`, where the label is its section texts joined by blank lines). The
retrieval eval scores against gold *spans*, so two chunking strategies are compared on
the same footing, and the UI can highlight the exact sentence a verdict cites.

Strategies:
  section  never crosses a section boundary; packs paragraphs, list items and table rows
           up to `max_words`; a chunk cut from the middle of a table carries the table's
           caption and header rows as `context`.
  fixed    sliding word windows over the whole label, blind to sections (the baseline).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from onlabel.data.parse_spl import Label

SECTION_SEP = "\n\n"
SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\[•-])")


@dataclass
class Chunk:
    chunk_id: str
    label_key: str
    set_id: str
    version: int
    drug: str
    ingredient: str
    section_index: int
    section_path: str
    top_code: str
    number: str | None
    start: int  # offsets into the section's text
    end: int
    doc_start: int  # offsets into the whole label
    doc_end: int
    text: str
    context: str = ""  # table caption + header rows when the chunk starts mid-table

    def header(self) -> str:
        return f"{self.drug} ({self.ingredient}) | {self.section_path}"

    def embed_text(self) -> str:
        parts = [self.header(), self.context, self.text]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)


def section_offsets(label: Label) -> list[int]:
    """Start of each section in the joined label text."""
    starts, pos = [], 0
    for sec in label.sections:
        starts.append(pos)
        pos += len(sec.text) + len(SECTION_SEP)
    return starts


def label_doc(label: Label) -> str:
    return SECTION_SEP.join(s.text for s in label.sections)


def _blocks(text: str) -> list[tuple[int, int]]:
    """(start, end) of each blank-line-separated block."""
    out, pos = [], 0
    for m in re.finditer(r"\n\s*\n", text):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    return out


def _is_table(block: str) -> bool:
    lines = block.split("\n")
    return len(lines) >= 2 and sum(" | " in ln or ln.startswith("| ") for ln in lines) >= 2


def _units(text: str, max_words: int) -> list[tuple[int, int, str]]:
    """(start, end, table_context) for units small enough to pack."""
    units: list[tuple[int, int, str]] = []
    blocks = _blocks(text)
    for bi, (bs, be) in enumerate(blocks):
        block = text[bs:be]
        if _is_table(block):
            lines, pos = [], bs
            for ln in block.split("\n"):
                lines.append((pos, pos + len(ln)))
                pos += len(ln) + 1
            n_header = 2 if len(lines) > 4 else 1
            caption = ""
            if bi > 0:
                prev = text[blocks[bi - 1][0] : blocks[bi - 1][1]]
                if prev.lower().startswith("table") and len(prev) < 300:
                    caption = prev
            header = "\n".join(text[s:e] for s, e in lines[:n_header])
            ctx = "\n".join(p for p in (caption, header) if p)
            units.append((lines[0][0], lines[n_header - 1][1], ""))  # header rows travel together
            units.extend((s, e, ctx) for s, e in lines[n_header:])
        elif len(block.split()) > max_words:
            pos = bs
            for piece in SENTENCE_END.split(block):
                start = text.index(piece, pos)
                units.append((start, start + len(piece), ""))
                pos = start + len(piece)
        else:
            units.append((bs, be, ""))
    return units


def _pack(units: list[tuple[int, int, str]], text: str, max_words: int) -> list[list[tuple[int, int, str]]]:
    """Greedily group consecutive units into chunks of at most `max_words` words."""
    groups: list[list[tuple[int, int, str]]] = []
    group: list[tuple[int, int, str]] = []
    words = 0
    for unit in units:
        n_words = len(text[unit[0] : unit[1]].split())
        if group and words + n_words > max_words:
            groups.append(group)
            group, words = [], 0
        group.append(unit)
        words += n_words
    if group:
        groups.append(group)
    return groups


def section_chunks(label: Label, label_key: str, ingredient: str, max_words: int = 180) -> list[Chunk]:
    chunks: list[Chunk] = []
    starts = section_offsets(label)
    drug = label.products[0] if label.products else label_key.upper()
    for si, sec in enumerate(label.sections):
        for n, group in enumerate(_pack(_units(sec.text, max_words), sec.text, max_words)):
            s, e = group[0][0], group[-1][1]
            chunks.append(
                Chunk(
                    chunk_id=f"{label_key}:v{label.version}:{si}:{n}",
                    label_key=label_key, set_id=label.set_id, version=label.version,
                    drug=drug, ingredient=ingredient, section_index=si,
                    section_path=sec.path, top_code=sec.top_code, number=sec.number,
                    start=s, end=e, doc_start=starts[si] + s, doc_end=starts[si] + e,
                    text=sec.text[s:e],
                    context=group[0][2],  # only set when the chunk starts below a table header
                )
            )
    return chunks


def fixed_chunks(
    label: Label, label_key: str, ingredient: str, window: int = 180, overlap: int = 30
) -> list[Chunk]:
    doc = label_doc(label)
    starts = section_offsets(label)
    drug = label.products[0] if label.products else label_key.upper()
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", doc)]
    chunks: list[Chunk] = []
    step = window - overlap
    for n, i in enumerate(range(0, max(1, len(spans) - overlap), step)):
        ds, de = spans[i][0], spans[min(i + window, len(spans)) - 1][1]
        si = max(j for j, st in enumerate(starts) if st <= ds)
        sec = label.sections[si]
        chunks.append(
            Chunk(
                chunk_id=f"{label_key}:v{label.version}:fixed:{n}",
                label_key=label_key, set_id=label.set_id, version=label.version,
                drug=drug, ingredient=ingredient, section_index=si,
                section_path=sec.path, top_code=sec.top_code, number=sec.number,
                start=ds - starts[si], end=min(de - starts[si], len(sec.text)),
                doc_start=ds, doc_end=de, text=doc[ds:de],
            )
        )
    return chunks
