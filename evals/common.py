"""Shared pieces for the eval scripts: loading the benchmark, intervals, report writing."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Sequence
from pathlib import Path

CLAIMS = Path("evals/bench/claims.jsonl")
REPORTS = Path("reports")


def load_claims(split: str | None = None) -> list[dict]:
    claims = [json.loads(line) for line in CLAIMS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [c for c in claims if split in (None, "all", c["split"])]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def cluster_bootstrap(items: Sequence[dict], stat: Callable[[list[dict]], float | None], key: str = "card",
                      n_boot: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    """95% percentile interval, resampling whole cards: claims written from one card share
    their evidence, so they are not independent draws."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it[key], []).append(it)
    keys = sorted(groups)
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        sample = [x for k in (rng.choice(keys) for _ in keys) for x in groups[k]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return (round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3))


def write_report(name: str, payload: dict, markdown: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{name}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
    (REPORTS / f"{name}.md").write_text(markdown, encoding="utf-8", newline="\n")
