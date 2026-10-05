"""The retrieval index: label chunks, their embeddings, BM25 statistics, and hybrid search.

Exact search in numpy. The corpus is a few thousand chunks, so a dot product over all of
them takes milliseconds and a vector database would add memory and moving parts to a
512 MB instance without adding anything. Dense and BM25 rankings are fused with
reciprocal-rank fusion, written out here so each half can be switched off in ablations.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from onlabel.data.chunk import Chunk
from onlabel.retrieval.bm25 import BM25, tokenize
from onlabel.retrieval.encoder import OnnxEncoder

RRF_K = 60
NUMBER_TOKEN = re.compile(r"^\d+(?:[.,]\d+)*$")
RARE_NUMBER_DF = 10  # a figure in at most this many chunks is specific enough to pin
PINNED_FOR_NUMBERS = 2


@dataclass
class Hit:
    chunk: Chunk
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    number_rank: int | None = None


@dataclass
class LabelIndex:
    chunks: list[Chunk]
    embeddings: np.ndarray  # (n, dim) float32, L2-normalised
    bm25: BM25
    meta: dict = field(default_factory=dict)

    @classmethod
    def build(cls, chunks: list[Chunk], encoder: OnnxEncoder, meta: dict | None = None) -> LabelIndex:
        texts = [c.embed_text() for c in chunks]
        return cls(chunks, encoder.encode(texts), BM25.build(texts), meta or {})

    # -- persistence ---------------------------------------------------------------------
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "chunks.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(json.dumps(c.to_dict(), ensure_ascii=False) + "\n" for c in self.chunks)
        np.save(directory / "embeddings.npy", self.embeddings.astype(np.float16))
        self.bm25.save(directory)
        meta = {**self.meta, "n_chunks": len(self.chunks), "built_at": datetime.now(UTC).isoformat(timespec="seconds")}
        (directory / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")

    @classmethod
    def load(cls, directory: Path) -> LabelIndex:
        with open(directory / "chunks.jsonl", encoding="utf-8") as fh:
            chunks = [Chunk(**json.loads(line)) for line in fh]
        emb = np.load(directory / "embeddings.npy").astype(np.float32)
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        return cls(chunks, emb, BM25.load(directory), meta)

    # -- search --------------------------------------------------------------------------
    def mask(self, labels: list[str] | None = None, top_codes: list[str] | None = None) -> np.ndarray:
        m = np.ones(len(self.chunks), dtype=bool)
        if labels:
            wanted = set(labels)
            m &= np.array([c.label_key in wanted for c in self.chunks])
        if top_codes:
            codes = set(top_codes)
            m &= np.array([c.top_code in codes for c in self.chunks])
        return m

    def search(
        self,
        query: str,
        query_vec: np.ndarray | None,
        k: int = 8,
        *,
        labels: list[str] | None = None,
        top_codes: list[str] | None = None,
        use_dense: bool = True,
        use_bm25: bool = True,
        use_numbers: bool = True,
        depth: int = 50,
    ) -> list[Hit]:
        allowed = self.mask(labels, top_codes)
        candidates = np.flatnonzero(allowed)
        if len(candidates) == 0:
            return []
        fused: dict[int, float] = {}
        ranks: dict[str, dict[int, int]] = {"dense": {}, "bm25": {}, "numbers": {}}

        def fuse(name: str, order: np.ndarray) -> None:
            for r, i in enumerate(order[:depth]):
                ranks[name][int(i)] = r + 1
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (RRF_K + r + 1)

        bm25_all = self.bm25.scores(query) if (use_bm25 or use_numbers) else None
        if use_dense and query_vec is not None:
            sims = self.embeddings[candidates] @ query_vec
            fuse("dense", candidates[np.argsort(-sims)])
        if use_bm25:
            scores = bm25_all[candidates]
            positive = scores > 0  # a zero score is not a match; it must not enter fusion
            fuse("bm25", candidates[positive][np.argsort(-scores[positive])])
        pinned: list[int] = []
        if use_numbers:
            # Third signal for claims with figures. Table rows of bare numbers embed poorly
            # and drown in BM25, yet they are where efficacy figures live. Ranking alone was
            # not enough (a chunk strong on two lexical signals but absent from the dense
            # list still lost), so the chunks holding a claim's rare figures are pinned:
            # the judge always sees where a stated number is, or that it is nowhere.
            weights, rare = self.number_matches(query)
            weights = weights[candidates]
            has = weights > 0
            if has.any():
                tie = bm25_all[candidates][has] * 1e-6
                order = candidates[has][np.argsort(-(weights[has] + tie))]
                fuse("numbers", order)
                if rare:
                    pinned = [int(i) for i in order[:PINNED_FOR_NUMBERS]]

        rest = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1]) if i not in pinned]
        chosen = (pinned + rest)[:k]
        return [Hit(self.chunks[i], fused[i], ranks["dense"].get(i), ranks["bm25"].get(i), ranks["numbers"].get(i))
                for i in chosen]

    def number_matches(self, query: str) -> tuple[np.ndarray, bool]:
        """Per chunk: IDF-weighted count of the query's numbers it contains, and whether the
        query has any rare (specific) figure at all."""
        out = np.zeros(len(self.chunks), dtype=np.float32)
        rare = False
        n = self.bm25.n_docs
        for tok in {t for t in tokenize(query) if NUMBER_TOKEN.match(t)}:
            i = self.bm25.vocab.get(tok)
            if i is None:
                continue
            lo, hi = self.bm25.offsets[i], self.bm25.offsets[i + 1]
            df = int(hi - lo)
            rare |= df <= RARE_NUMBER_DF
            out[self.bm25.doc_ids[lo:hi]] += np.log(1 + (n - df + 0.5) / (df + 0.5))
        return out, rare
