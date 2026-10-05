"""Retrieval eval (Set A): does the label text a claim depends on reach the judge?

    uv run python -m evals.retrieval_eval
    uv run python -m evals.retrieval_eval --index scratch/index_fixed --name fixed

Gold is the character span of each card quote inside its label, so chunkings of any shape
are scored on the same footing: a retrieved chunk is relevant when it overlaps a gold span
of the claim's own label. Every benchmark claim is used, perturbed ones included: a claim
that inflates a figure still needs the row with the real figure in front of the judge.

Configurations, cumulative: dense only, BM25 only, the two fused (RRF), plus figure
pinning, plus section routing (what the API runs: 5 hits, routed sections first, 6 max).
Each runs with the label filter the API always applies, and without it as a stress test.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from evals.common import load_claims, wilson, write_report
from onlabel.models import BGE_SMALL_INT8
from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder
from onlabel.retrieval.index import LabelIndex
from onlabel.review import MAX_EXCERPTS, gather

CONFIGS = {
    "dense": {"use_bm25": False, "use_numbers": False},
    "bm25": {"use_dense": False, "use_numbers": False},
    "hybrid": {"use_numbers": False},
    "hybrid+figures": {},
    "production": {"routed": True},
}
KS = (1, 3, 5, 10)
API_K = 5


def relevant(chunk, claim: dict) -> bool:
    return chunk.label_key == claim["label"] and any(
        chunk.doc_start < s["doc_end"] and chunk.doc_end > s["doc_start"] for s in claim["gold_spans"])


def ranked(index: LabelIndex, claim: dict, qvec, cfg: dict, filtered: bool, k: int) -> list:
    labels = [claim["label"]] if filtered else None
    if cfg.get("routed"):  # the reviewer's own assembly, exactly as the API runs it
        hits, _ = gather(index, claim["text"], qvec, labels, claim["kind"], k=API_K)
        return [h.chunk for h in hits]
    hits = index.search(claim["text"], qvec, k=k, labels=labels, **cfg)
    return [h.chunk for h in hits]


def evaluate(index: LabelIndex, encoder: OnnxEncoder, claims: list[dict]) -> dict:
    qvecs = {c["id"]: encoder.encode_query(c["text"]) for c in claims}
    out = {}
    for name, cfg in CONFIGS.items():
        for filtered in (True, False):
            key = f"{name}{'' if filtered else ' (no label filter)'}"
            first_hit, per_claim = [], {}
            t = time.perf_counter()
            for c in claims:
                chunks = ranked(index, c, qvecs[c["id"]], cfg, filtered, k=max(KS))
                rank = next((i + 1 for i, ch in enumerate(chunks) if relevant(ch, c)), None)
                first_hit.append(rank)
                per_claim[c["id"]] = rank
            n = len(claims)
            row = {"n": n, "ms_per_claim": round((time.perf_counter() - t) * 1000 / n, 1)}
            for k in KS:
                if cfg.get("routed") and k > MAX_EXCERPTS:
                    continue
                hit = sum(1 for r in first_hit if r is not None and r <= k)
                row[f"hit@{k}"] = round(hit / n, 3)
                row[f"hit@{k}_ci"] = wilson(hit, n)
            if cfg.get("routed"):
                hit = sum(1 for r in first_hit if r is not None)
                row["hit@all"] = round(hit / n, 3)
                row["hit@all_ci"] = wilson(hit, n)
            row["mrr@10"] = round(sum(1 / r for r in first_hit if r is not None and r <= 10) / n, 3)
            cutoff = MAX_EXCERPTS if cfg.get("routed") else API_K  # what the judge would see
            row["misses"] = sorted(cid for cid, r in per_claim.items() if r is None or r > cutoff)
            out[key] = row
    return out


def markdown(name: str, meta: dict, results: dict, splits: dict) -> str:
    intro = (f"Index `{meta['index']}` ({meta['strategy']} chunks, {meta['n_chunks']} of them), "
             f"{meta['n_claims']} benchmark claims. A hit is a chunk overlapping the gold label span. "
             "`production` is what the API sends the judge: 5 hits plus up to 2 routed-section excerpts, 6 at most.")
    lines = [f"# Retrieval eval: {name}", "", intro, "",
             "| Configuration | hit@1 | hit@3 | hit@5 | hit@10 (production: all) | MRR@10 |",
             "|---|---|---|---|---|---|"]
    for key, row in results.items():
        last = row.get("hit@all", row.get("hit@10"))
        lines.append(f"| {key} | {row['hit@1']:.2f} | {row['hit@3']:.2f} | {row['hit@5']:.2f} | {last:.2f} | {row['mrr@10']:.2f} |")
    lines += ["", "95% Wilson intervals are in the JSON. By split (production, label filter on):", ""]
    for split, row in splits.items():
        lines.append(f"- {split}: hit@5 {row['hit@5']:.2f}, all excerpts {row['hit@all']:.2f} (n={row['n']})")
    prod = results["production"]
    lines += ["", f"Claims whose gold span is not among the judge's excerpts (production): {len(prod['misses'])}", ""]
    lines += [f"- `{m}`" for m in prod["misses"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=Path("data/index"))
    ap.add_argument("--name", default="section")
    args = ap.parse_args()

    index = LabelIndex.load(args.index)
    encoder = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path, query_prefix=BGE_QUERY_PREFIX)
    claims = load_claims()
    results = evaluate(index, encoder, claims)
    splits = {}
    for split in ("dev", "test"):
        sub = [c for c in claims if c["split"] == split]
        row = evaluate_one(index, encoder, sub)
        splits[split] = row
    meta = {"index": str(args.index).replace("\\", "/"), "strategy": index.meta.get("strategy"),
            "n_chunks": len(index.chunks), "n_claims": len(claims), "built_at": index.meta.get("built_at")}
    payload = {"meta": meta, "results": results, "by_split_production": splits}
    write_report(f"retrieval_{args.name}", payload, markdown(args.name, meta, results, splits))
    for key, row in results.items():
        last = row.get("hit@all", row.get("hit@10"))
        print(f"{key:36} hit@1 {row['hit@1']:.2f}  hit@5 {row['hit@5']:.2f}  hit@10/all {last:.2f}  mrr {row['mrr@10']:.2f}")
    return 0


def evaluate_one(index: LabelIndex, encoder: OnnxEncoder, claims: list[dict]) -> dict:
    """Production configuration, label filter on: the number that matters for the API."""
    n, hit5, hit_all = len(claims), 0, 0
    for c in claims:
        chunks = ranked(index, c, encoder.encode_query(c["text"]), CONFIGS["production"], True, k=max(KS))
        rank = next((i + 1 for i, ch in enumerate(chunks) if relevant(ch, c)), None)
        hit5 += rank is not None and rank <= 5
        hit_all += rank is not None
    return {"n": n, "hit@5": round(hit5 / n, 3), "hit@all": round(hit_all / n, 3)}


if __name__ == "__main__":
    raise SystemExit(main())
