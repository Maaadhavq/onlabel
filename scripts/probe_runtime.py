"""Measure what the runtime models cost: resident memory and single-thread latency.

Run it natively for a baseline, then inside the Docker image with the Render free-tier
limits to see the numbers that matter:

    docker run --rm --memory=512m --cpus=0.1 onlabel-api python scripts/probe_runtime.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlabel.sysinfo import rss_mb

QUERY = "Wegovy helps adults lose an average of 15% of their body weight in 68 weeks"
PASSAGE = (
    "In STEP 1, adults with obesity treated with WEGOVY 2.4 mg once weekly had a mean change "
    "in body weight of -14.9% from baseline to week 68, compared with -2.4% with placebo. "
) * 2


def timed(fn, n: int) -> list[float]:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def main() -> int:
    report: dict[str, object] = {"rss_start_mb": round(rss_mb(), 1)}

    import numpy as np
    import onnxruntime  # noqa: F401
    from tokenizers import Tokenizer

    from onlabel.models import BGE_SMALL_INT8, MINILM_RERANK_INT8
    from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder, session_options

    report["rss_after_imports_mb"] = round(rss_mb(), 1)

    enc = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path, query_prefix=BGE_QUERY_PREFIX)
    report["rss_after_encoder_mb"] = round(rss_mb(), 1)
    enc.encode_query(QUERY)  # warm-up
    q_ms = timed(lambda: enc.encode_query(QUERY), 10)
    report["encode_query_ms_p50"] = round(statistics.median(q_ms), 1)

    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(MINILM_RERANK_INT8.onnx_path), sess_options=session_options(1), providers=["CPUExecutionProvider"]
    )
    tok = Tokenizer.from_file(str(MINILM_RERANK_INT8.tokenizer_path))
    tok.enable_truncation(max_length=256)
    tok.enable_padding(pad_id=0, pad_token="[PAD]")
    report["rss_after_reranker_mb"] = round(rss_mb(), 1)

    names = {i.name for i in sess.get_inputs()}

    def score_pairs(k: int) -> None:
        batch = tok.encode_batch([(QUERY, PASSAGE)] * k)
        feeds = {
            "input_ids": np.array([e.ids for e in batch], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in batch], dtype=np.int64),
        }
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in batch], dtype=np.int64)
        sess.run(None, feeds)

    score_pairs(1)
    report["rerank_1_pair_ms_p50"] = round(statistics.median(timed(lambda: score_pairs(1), 5)), 1)
    report["rerank_10_pairs_ms_p50"] = round(statistics.median(timed(lambda: score_pairs(10), 3)), 1)
    report["rss_after_rerank_mb"] = round(rss_mb(), 1)

    passages = [PASSAGE] * 64
    t = time.perf_counter()
    enc.encode(passages)
    report["encode_64_passages_s"] = round(time.perf_counter() - t, 2)
    report["rss_end_mb"] = round(rss_mb(), 1)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
