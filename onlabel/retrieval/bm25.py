"""Okapi BM25 in numpy, with a tokenizer that keeps numbers whole.

Promotional claims hinge on numbers ("14.9%", "2.4 mg", "68 weeks"). A default word
tokenizer splits "14.9%" into "14" and "9" and the exact-figure match that BM25 is good at
is lost, so numbers keep their decimals. The percent sign and minus sign are dropped:
claims say "14.9%" while efficacy tables say "-14.9" in a "% change" column, and keeping
either sign made that match impossible (it cost the first skeleton run a true claim).
Hyphenated terms stay whole ("c-cell", "non-fatal"). About forty lines, so no dependency.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
STOP = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from", "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "which", "who", "than", "then", "there", "these", "those", "into", "after", "before", "during"]
)


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower().translate(DASHES)) if t not in STOP]


class BM25:
    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.vocab: dict[str, int] = {}
        self.offsets = np.zeros(1, dtype=np.int64)  # postings of term t: [offsets[t], offsets[t+1])
        self.doc_ids = np.zeros(0, dtype=np.int32)
        self.tfs = np.zeros(0, dtype=np.float32)
        self.doc_len = np.zeros(0, dtype=np.float32)

    @classmethod
    def build(cls, texts: list[str], **kw) -> BM25:
        bm = cls(**kw)
        postings: dict[str, dict[int, int]] = {}
        lens = []
        for d, text in enumerate(texts):
            toks = tokenize(text)
            lens.append(len(toks))
            for t in toks:
                postings.setdefault(t, {}).setdefault(d, 0)
                postings[t][d] += 1
        terms = sorted(postings)
        bm.vocab = {t: i for i, t in enumerate(terms)}
        sizes = [len(postings[t]) for t in terms]
        bm.offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
        bm.doc_ids = np.fromiter((d for t in terms for d in postings[t]), dtype=np.int32)
        bm.tfs = np.fromiter((c for t in terms for c in postings[t].values()), dtype=np.float32)
        bm.doc_len = np.array(lens, dtype=np.float32)
        return bm

    @property
    def n_docs(self) -> int:
        return len(self.doc_len)

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n_docs, dtype=np.float32)
        if self.n_docs == 0:
            return out
        avgdl = float(self.doc_len.mean()) or 1.0
        for t in set(tokenize(query)):
            i = self.vocab.get(t)
            if i is None:
                continue
            lo, hi = self.offsets[i], self.offsets[i + 1]
            docs, tf = self.doc_ids[lo:hi], self.tfs[lo:hi]
            df = hi - lo
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            norm = tf + self.k1 * (1 - self.b + self.b * self.doc_len[docs] / avgdl)
            out[docs] += idf * tf * (self.k1 + 1) / norm
        return out

    def save(self, directory: Path) -> None:
        np.savez_compressed(
            directory / "bm25.npz", offsets=self.offsets, doc_ids=self.doc_ids, tfs=self.tfs, doc_len=self.doc_len
        )
        terms = sorted(self.vocab, key=self.vocab.get)
        (directory / "bm25_vocab.json").write_text(
            json.dumps({"k1": self.k1, "b": self.b, "terms": terms}), encoding="utf-8", newline="\n"
        )

    @classmethod
    def load(cls, directory: Path) -> BM25:
        meta = json.loads((directory / "bm25_vocab.json").read_text(encoding="utf-8"))
        bm = cls(meta["k1"], meta["b"])
        bm.vocab = {t: i for i, t in enumerate(meta["terms"])}
        arrays = np.load(directory / "bm25.npz")
        bm.offsets, bm.doc_ids = arrays["offsets"], arrays["doc_ids"]
        bm.tfs, bm.doc_len = arrays["tfs"], arrays["doc_len"]
        return bm
