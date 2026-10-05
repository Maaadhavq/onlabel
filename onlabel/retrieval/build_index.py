"""Chunk the parsed labels, embed them, and write the index the API serves.

    uv run python -m onlabel.retrieval.build_index                     # section strategy
    uv run python -m onlabel.retrieval.build_index --strategy fixed --out data/index_fixed
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from onlabel.data.chunk import fixed_chunks, section_chunks
from onlabel.data.corpus import LABELS_DIR, MANIFEST
from onlabel.data.parse_spl import Label
from onlabel.models import BGE_SMALL_INT8
from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder
from onlabel.retrieval.index import LabelIndex


def load_labels(keys: list[str] | None = None) -> dict[str, tuple[Label, dict]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for key, entry in sorted(manifest.items()):
        if keys and key not in keys:
            continue
        label = Label.from_dict(json.loads((LABELS_DIR / f"{key}.json").read_text(encoding="utf-8")))
        out[key] = (label, entry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=["section", "fixed"], default="section")
    ap.add_argument("--max-words", type=int, default=180)
    ap.add_argument("--out", type=Path, default=Path("data/index"))
    ap.add_argument("labels", nargs="*")
    args = ap.parse_args()

    chunks = []
    labels = load_labels(args.labels or None)
    for key, (label, entry) in labels.items():
        if args.strategy == "section":
            got = section_chunks(label, key, entry["ingredient"], args.max_words)
        else:
            got = fixed_chunks(label, key, entry["ingredient"], window=args.max_words)
        chunks.extend(got)
        print(f"  {key:10} {len(got):5} chunks")

    # The arena is fine offline (one big batch job) and makes embedding faster.
    enc = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path,
                      query_prefix=BGE_QUERY_PREFIX, threads=4, arena=True)
    t = time.perf_counter()
    index = LabelIndex.build(
        chunks, enc,
        meta={
            "strategy": args.strategy, "max_words": args.max_words, "encoder": BGE_SMALL_INT8.key,
            "encoder_revision": BGE_SMALL_INT8.revision,
            "labels": {k: {"set_id": e["set_id"], "version": e["version"]} for k, (_, e) in labels.items()},
        },
    )
    index.save(args.out)
    print(f"indexed {len(chunks)} chunks in {time.perf_counter() - t:.1f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
