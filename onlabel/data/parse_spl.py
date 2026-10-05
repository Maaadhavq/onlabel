"""Parse a DailyMed SPL document into numbered label sections with plain text.

stdlib `xml.etree` only: lxml's DLL is blocked on the dev machine and the runtime image
does not need it. Sections are identified by LOINC code (34067-9 is Indications and Usage
on every label); numbered subsections ("5.1 Risk of Thyroid C-Cell Tumors") usually carry
the generic code 42229-5, so their number comes from the title.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

V3 = "{urn:hl7-org:v3}"
NS = {"v3": "urn:hl7-org:v3"}

# Top-level sections worth checking a promotional claim against.
TOP_SECTIONS = {
    "34066-1": "Boxed Warning",
    "34067-9": "Indications and Usage",
    "34068-7": "Dosage and Administration",
    "43678-2": "Dosage Forms and Strengths",
    "34070-3": "Contraindications",
    "43685-7": "Warnings and Precautions",
    "34071-1": "Warnings",  # pre-2006 label format
    "42232-9": "Precautions",  # pre-2006 label format
    "34084-4": "Adverse Reactions",
    "34073-7": "Drug Interactions",
    "43684-0": "Use in Specific Populations",
    "34088-5": "Overdosage",
    "34089-3": "Description",
    "34090-1": "Clinical Pharmacology",
    "43680-8": "Nonclinical Toxicology",
    "34092-7": "Clinical Studies",
    "34069-5": "How Supplied/Storage and Handling",
    "34076-0": "Patient Counseling Information",
    "42231-1": "Medication Guide",
}
# Product data, recent major changes, carton images, instructions for use: never evidence.
SKIPPED_SECTIONS = {"48780-1", "43683-2", "51945-4", "59845-8"}

NUMBERED_TITLE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.*)$")
# Many labels encode a sub-bullet as a sibling item whose marker is "o" rather than as a
# nested list. The sub-items qualify their parent ("in: adults and pediatric patients aged
# 12 years and older"), so the indent has to survive.
SUB_BULLETS = {"o", "◦", "▪", "○", "-", "–", "−"}
FOOTNOTE_MARK = re.compile(r"^[a-z*†‡§¶#]{1,2}$", re.IGNORECASE)


@dataclass
class LabelSection:
    code: str  # LOINC code of this (sub)section
    top_code: str  # LOINC code of the top-level section it sits under
    top_name: str
    number: str | None  # "5.1"; None for the boxed warning and the medication guide
    title: str
    path: str  # "5 WARNINGS AND PRECAUTIONS > 5.1 Risk of Thyroid C-Cell Tumors"
    text: str  # this section's own text, children excluded


@dataclass
class Label:
    set_id: str
    version: int
    effective_time: str  # YYYYMMDD
    products: list[str]  # brand names on the label, e.g. ["WEGOVY"]
    generic: str
    sections: list[LabelSection] = field(default_factory=list)
    skipped_codes: list[str] = field(default_factory=list)  # unknown top-level codes, for review

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Label:
        return cls(**{**d, "sections": [LabelSection(**s) for s in d["sections"]]})


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _flat(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def render(el: ET.Element) -> str:
    """HL7 narrative block -> plain text. Paragraphs and list items become lines, tables
    become `cell | cell` rows, images are dropped."""
    out: list[str] = []
    if el.text:
        out.append(el.text)
    for child in el:
        _render(child, out)
    lines = [_tidy_line(ln) for ln in "".join(out).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _tidy_line(line: str) -> str:
    """Collapse whitespace, but keep the indent of a nested bullet (written by `_item`)."""
    indent = re.match(r"^( *)- ", line)
    body = re.sub(r"[ \t ]+", " ", line).strip()
    return (indent.group(1) + body) if indent else body


def _render(el: ET.Element, out: list[str]) -> None:
    tag = _local(el.tag)
    if tag in ("renderMultiMedia", "observationMedia"):
        pass
    elif tag == "table":
        out.append("\n\n")
        _table(el, out)
        out.append("\n\n")
    elif tag == "br":
        out.append("\n")
    elif tag == "sup":
        inner = _flat(el)
        if inner and not FOOTNOTE_MARK.match(inner):  # keep exponents, drop footnote marks
            out.append("^" + inner)
    elif tag == "list":
        out.append("\n")
        for child in el:
            ctag = _local(child.tag)
            if ctag == "item":
                _item(child, out, depth=0)
            elif ctag == "caption" and _flat(child):
                out.append("\n" + _flat(child))
        out.append("\n\n")
    else:
        block = tag in ("paragraph", "caption", "footnote")
        out.append("\n\n" if block else "")
        if el.text:
            out.append(el.text)
        for child in el:
            _render(child, out)
        if block:
            out.append("\n\n")
    if el.tail:
        out.append(el.tail)


def _item(item: ET.Element, out: list[str], depth: int) -> None:
    """One list item on one line. SPL puts the bullet glyph ("•", "o", "-") in a <caption>
    and the content in <paragraph>s; rendered naively that is three lines per bullet."""
    buf: list[str] = [item.text or ""]
    nested: list[ET.Element] = []
    for child in item:
        ctag = _local(child.tag)
        if ctag == "caption" and len(_flat(child)) <= 3:
            if _flat(child) in SUB_BULLETS and depth == 0:  # flat list faking a sub-bullet
                depth = 1
        elif ctag == "list":
            nested.append(child)
        else:
            _render(child, buf)
            continue
        if child.tail:
            buf.append(child.tail)
    text = " ".join("".join(buf).split())
    if text:
        out.append("\n" + "  " * depth + "- " + text)
    for lst in nested:
        for sub in lst:
            if _local(sub.tag) == "item":
                _item(sub, out, depth + 1)


def _table(table: ET.Element, out: list[str]) -> None:
    caption = _flat(table.find("v3:caption", NS))
    if caption:
        out.append(caption + "\n")
    for tr in table.iter(V3 + "tr"):
        cells = []
        for cell in tr:
            if _local(cell.tag) in ("td", "th"):
                parts: list[str] = [cell.text or ""]
                for child in cell:
                    _render(child, parts)
                cells.append(" ".join("".join(parts).split()))
        if any(cells):
            out.append(" | ".join(cells) + "\n")


def _walk(sec: ET.Element, top_code: str, top_name: str, parents: list[str], out: list[LabelSection]) -> None:
    code_el = sec.find("v3:code", NS)
    code = code_el.get("code", "") if code_el is not None else ""
    raw_title = _flat(sec.find("v3:title", NS))
    m = NUMBERED_TITLE.match(raw_title)
    number, title = (m.group(1), m.group(2)) if m else (None, raw_title or top_name)
    part = f"{number} {title}" if number else title
    path = parents + [part]

    text_el = sec.find("v3:text", NS)
    text = render(text_el) if text_el is not None else ""
    if text:
        out.append(LabelSection(code, top_code, top_name, number, title, " > ".join(path), text))
    for comp in sec.findall("v3:component", NS):
        sub = comp.find("v3:section", NS)
        if sub is not None:
            _walk(sub, top_code, top_name, path, out)


def parse_spl(xml_bytes: bytes) -> Label:
    root = ET.fromstring(xml_bytes)
    set_id = root.find("v3:setId", NS).get("root")
    version = int(root.find("v3:versionNumber", NS).get("value"))
    effective = root.find("v3:effectiveTime", NS).get("value")[:8]

    products: list[str] = []
    for name in root.findall(".//v3:manufacturedProduct/v3:manufacturedProduct/v3:name", NS):
        n = _flat(name).upper()
        if n and n not in products:
            products.append(n)
    generic = _flat(root.find(".//v3:genericMedicine/v3:name", NS)).lower()

    label = Label(set_id, version, effective, products, generic)
    body = root.find(".//v3:structuredBody", NS)
    for comp in body.findall("v3:component", NS):
        sec = comp.find("v3:section", NS)
        if sec is None:
            continue
        code_el = sec.find("v3:code", NS)
        code = code_el.get("code", "") if code_el is not None else ""
        if code in TOP_SECTIONS:
            _walk(sec, code, TOP_SECTIONS[code], [], label.sections)
        elif code not in SKIPPED_SECTIONS:
            label.skipped_codes.append(code)
    return label
