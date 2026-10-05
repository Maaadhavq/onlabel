"""Run the real pipeline on the sample documents and save their event streams for the page.

The page ships these files, so a sample opens instantly even while the free server sleeps
or the model quotas are spent. Model answers land in the committed cache (cache/llm), so a
rerun reproduces the files without API keys.

    uv run python scripts/make_samples.py            # all samples
    uv run python scripts/make_samples.py ozempic-web-banner
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlabel.env import load_env

load_env()

from onlabel.agent.rewrite import suggest_rewrite
from onlabel.api.main import SPLIT_CHAIN
from onlabel.llm.cache import ResponseCache
from onlabel.llm.client import LLMClient
from onlabel.llm.registry import DEMO_CHAIN
from onlabel.models import BGE_SMALL_INT8
from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder
from onlabel.retrieval.index import LabelIndex
from onlabel.review import Reviewer

OUT = Path("web/src/samples")

SAMPLES = [
    {
        "id": "wegovy-spring-email",
        "title": "Wegovy spring email",
        "note": "Synthetic test copy.",
        "label": "wegovy",
        "audience": "consumer",
        "text": (
            "Your weight-loss journey starts here. Wegovy is approved for weight loss in children as young as 8. "
            "In clinical trials, adults lost an average of 14.9% of their body weight at 68 weeks. "
            "Wegovy also reduces the risk of heart attack and stroke. "
            "Unlike other options, Wegovy has no serious side effects. "
            "Use it with a reduced-calorie diet and increased physical activity. "
            "Ask your doctor if Wegovy is right for you."
        ),
    },
    {
        "id": "ozempic-web-banner",
        "title": "Ozempic web banner",
        "note": "Synthetic test copy. The first two lines echo claims FDA cited in its February 2026 "
                "untitled letter about the “There’s Only One Ozempic” TV ad.",
        "label": "ozempic",
        "audience": "consumer",
        "text": (
            "There's only one Ozempic. Ozempic is the GLP-1 with the most approved uses for adults with type 2 diabetes. "
            "It lowers A1C, and it may help you lose some weight too. "
            "Ozempic also reduces the risk of kidney failure. Ask your doctor about Ozempic."
        ),
    },
    {
        "id": "mounjaro-hcp-detail-aid",
        "title": "Mounjaro detail aid for HCPs",
        "note": "Synthetic test copy.",
        "label": "mounjaro",
        "audience": "hcp",
        "text": (
            "MOUNJARO is indicated as an adjunct to diet and exercise to improve glycemic control in adults and "
            "pediatric patients 10 years of age and older with type 2 diabetes mellitus. "
            "MOUNJARO is approved for chronic weight management in adults with obesity. "
            "In SURPASS-2, MOUNJARO provided greater A1C reduction than semaglutide 1 mg. "
            "MOUNJARO can be used in patients with a personal history of medullary thyroid carcinoma."
        ),
    },
]


def suggest_all(reviewer: Reviewer, index: LabelIndex, llm: LLMClient, events: list[dict], sample: dict) -> dict:
    """On-label wording for every flagged claim, each re-checked by the normal pipeline, so
    "Suggest on-label wording" works on a sample without the server."""
    claims = next((e["data"]["claims"] for e in events if e["event"] == "claims"), [])
    kinds = {c["n"]: c["kind"] for c in claims}
    out: dict[str, dict] = {}
    for ev in events:
        if ev["event"] != "claim" or ev["data"]["review"]["status"] == "supported":
            continue
        n, review = ev["data"]["n"], ev["data"]["review"]
        ids = [e["chunk_id"] for e in review["evidence"]] + [r["chunk_id"] for r in review["retrieved"][:3]]
        chunks = list({c.chunk_id: c for c in (index.get(i) for i in ids) if c}.values())
        res = suggest_rewrite(llm, review["claim"], review, chunks, sample["audience"])
        if res.data is None:
            print(f"  rewrite {n}: no model answered")
            continue
        check = reviewer.review_claim(res.data.rewrite, [sample["label"]], kind=kinds.get(n))
        out[str(n)] = {"rewrite": res.data.rewrite, "model": res.model_key, "review": check.to_dict()}
        print(f"  rewrite {n}: {check.status}")
    return out


def main() -> int:
    wanted = set(sys.argv[1:])
    index = LabelIndex.load(Path("data/index"))
    encoder = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path, query_prefix=BGE_QUERY_PREFIX)
    cache = ResponseCache("cache/llm")
    llm = LLMClient(DEMO_CHAIN, cache, wait_for_budget=True, timeout_s=60)
    splitter = LLMClient(SPLIT_CHAIN, cache, wait_for_budget=True, timeout_s=60, budget=llm.budget)
    reviewer = Reviewer(index, encoder, llm, splitter=splitter)
    OUT.mkdir(parents=True, exist_ok=True)

    for sample in SAMPLES:
        if wanted and sample["id"] not in wanted:
            continue
        events: list[dict] = []
        t = time.perf_counter()

        def emit(event: str, data: dict, events: list[dict] = events) -> None:
            events.append({"id": len(events), "event": event, "data": data})
            if event == "claim":
                r = data["review"]
                print(f"  claim {data['n']}: {r['status']:20} {r['model']}")

        print(sample["id"])
        reviewer.review_document(sample["text"], [sample["label"]], emit)
        rewrites = suggest_all(reviewer, index, llm, events, sample)
        payload = {**sample, "created": datetime.now(UTC).isoformat(timespec="seconds"),
                   "events": events, "rewrites": rewrites}
        path = OUT / f"{sample['id']}.json"
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"  wrote {path} ({len(events)} events, {time.perf_counter() - t:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
