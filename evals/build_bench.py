"""Build the claim benchmark from the hand-written fact cards.

    uv run python -m evals.build_bench

Every card quote must be found verbatim (exact, or after folding whitespace and dashes) in
its label; the run stops otherwise, so a gold span can never point at text the label does
not contain. A claim's expected verdict comes from how it was built (its op), never from a
model. Splits follow the active ingredient: semaglutide and tirzepatide labels were in
front of us while the prompts and guards were written (dev); the other six ingredients
were not (test).

Writes evals/bench/claims.jsonl.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from onlabel.agent.ground import locate
from onlabel.data.chunk import section_offsets
from onlabel.retrieval.build_index import load_labels

BENCH = Path("evals/bench")
CARDS = BENCH / "cards.json"
CLAIMS = BENCH / "claims.jsonl"

DEV_INGREDIENTS = {"semaglutide", "tirzepatide"}

# What each construction makes the claim. `accept` lists the verdicts that name the problem
# correctly; any verdict other than supported still keeps the claim away from approval.
EXPECT = {
    "faithful": {"gold": "supported", "accept": ["supported"], "violations": []},
    "drop_qualifier": {"gold": "needs_qualifier", "accept": ["needs_qualifier", "off_label", "unsupported"],
                       "violations": ["omitted_qualifier", "broadened_indication"]},
    "broaden": {"gold": "off_label", "accept": ["off_label", "contradicted", "unsupported"],
                "violations": ["broadened_indication"]},
    "inflate": {"gold": "contradicted", "accept": ["contradicted", "unsupported"],
                "violations": ["overstated_efficacy"]},
    "superiority": {"gold": "unsupported", "accept": ["unsupported", "contradicted"],
                    "violations": ["unsubstantiated_superiority"]},
    "absolute": {"gold": "unsupported", "accept": ["unsupported", "contradicted", "needs_qualifier"],
                 "violations": ["unsupported_absolute_claim", "overstated_efficacy"]},
    "deny_risk": {"gold": "contradicted", "accept": ["contradicted", "unsupported"], "violations": ["minimized_risk"]},
    "contradict": {"gold": "contradicted", "accept": ["contradicted", "off_label", "unsupported"],
                   "violations": ["minimized_risk", "broadened_indication"]},
    "wrong_dose": {"gold": "contradicted", "accept": ["contradicted", "off_label", "unsupported"], "violations": []},
}


def find_quote(label, quote: str) -> dict | None:
    """The quote's section and offsets (section and whole-label), exact or folded matches only."""
    starts = section_offsets(label)
    for si, sec in enumerate(label.sections):
        g = locate(sec.text, quote)
        if g.match in ("exact", "normalized"):
            return {"section": sec.path, "top_code": sec.top_code, "start": g.start, "end": g.end,
                    "doc_start": starts[si] + g.start, "doc_end": starts[si] + g.end}
    return None


def build() -> list[dict]:
    cards = json.loads(CARDS.read_text(encoding="utf-8"))["cards"]
    labels = load_labels()
    out, problems = [], []
    seen_ids = set()
    for card in cards:
        if card["id"] in seen_ids:
            problems.append(f"{card['id']}: duplicate card id")
        seen_ids.add(card["id"])
        label, entry = labels[card["label"]]
        spans = []
        for q in card["quotes"]:
            found = find_quote(label, q)
            if found is None:
                problems.append(f"{card['id']}: quote not in the {card['label']} label: {q[:70]!r}")
            else:
                spans.append(found)
        for i, claim in enumerate(card["claims"]):
            if claim["op"] not in EXPECT:
                problems.append(f"{card['id']}: unknown op {claim['op']!r}")
                continue
            out.append({
                "id": f"{card['id']}:{i}",
                "card": card["id"],
                "label": card["label"],
                "ingredient": entry["ingredient"],
                "split": "dev" if entry["ingredient"] in DEV_INGREDIENTS else "test",
                "kind": card["kind"],
                "op": claim["op"],
                "text": claim["text"],
                **EXPECT[claim["op"]],
                "gold_spans": spans,
                "label_version": label.version,
            })
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(f"{len(problems)} problem(s); nothing written")
    return out


def main() -> int:
    claims = build()
    with open(CLAIMS, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in claims)
    by = Counter((c["split"], c["op"]) for c in claims)
    print(f"{len(claims)} claims from {len({c['card'] for c in claims})} cards -> {CLAIMS}")
    for split in ("dev", "test"):
        n = sum(v for (s, _), v in by.items() if s == split)
        ops = ", ".join(f"{op} {v}" for (s, op), v in sorted(by.items()) if s == split)
        print(f"  {split:4} {n:3}  {ops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
