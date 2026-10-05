"""Which labels OnLabel indexes, and how each one is pinned to a DailyMed set_id.

`manufacturer` picks the maker's own label over repackager copies (DailyMed lists, for
example, an A-S Medication Solutions copy of Wegovy). `ingredient` drives the grouped
train/dev/test splits: sibling labels such as Ozempic, Wegovy and Rybelsus share text, so
they must land in the same split.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LABELS_DIR = Path("data/labels")
RAW_DIR = Path("data/raw/labels")
MANIFEST = LABELS_DIR / "manifest.json"


@dataclass(frozen=True)
class LabelSpec:
    key: str
    query: str  # DailyMed drug_name search
    manufacturer: str  # upper-case substring of the DailyMed title
    ingredient: str
    role: str  # "deep" (incretin class), "comparator", or "holdout"


CORPUS: dict[str, LabelSpec] = {
    s.key: s
    for s in [
        LabelSpec("wegovy", "wegovy", "NOVO NORDISK", "semaglutide", "deep"),
        LabelSpec("ozempic", "ozempic", "NOVO NORDISK", "semaglutide", "deep"),
        LabelSpec("rybelsus", "rybelsus", "NOVO NORDISK", "semaglutide", "deep"),
        LabelSpec("mounjaro", "mounjaro", "ELI LILLY", "tirzepatide", "deep"),
        LabelSpec("zepbound", "zepbound", "ELI LILLY", "tirzepatide", "deep"),
        LabelSpec("victoza", "victoza", "NOVO NORDISK", "liraglutide", "deep"),
        LabelSpec("saxenda", "saxenda", "NOVO NORDISK", "liraglutide", "deep"),
        LabelSpec("trulicity", "trulicity", "ELI LILLY", "dulaglutide", "deep"),
        LabelSpec("jardiance", "jardiance", "BOEHRINGER", "empagliflozin", "comparator"),
        LabelSpec("farxiga", "farxiga", "ASTRAZENECA", "dapagliflozin", "comparator"),
        LabelSpec("januvia", "januvia", "MERCK", "sitagliptin", "comparator"),
        LabelSpec("lantus", "lantus", "SANOFI", "insulin glargine", "comparator"),
    ]
}

SKELETON = ["wegovy", "ozempic", "mounjaro"]


def label_name(products: list[str], key: str) -> str:
    """How a label is named to reviewers and to the judge: every brand it covers, the one it
    is filed under first. Rybelsus's label also covers Ozempic tablets, and naming it by its
    first product called it "OZEMPIC", exactly like the Ozempic injection label."""
    names = [p for p in products if p] or [key.upper()]
    # MOUNJARO KWIKPEN is a presentation of MOUNJARO, not another brand.
    brands = [p for p in names if not any(p != q and p.startswith(q + " ") for q in names)]
    brands.sort(key=lambda p: p.lower() != key.lower())
    return " and ".join(brands)
