"""Sentence encoder on plain onnxruntime + tokenizers, no torch.

The deployed API has about 0.1 CPU and 512 MB, so the runtime carries no PyTorch. This
class is also what embeds the corpus offline, so documents and queries go through the
same graph and the same tokenizer; a mismatch there quietly costs recall.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

# bge v1.5 was trained with this instruction on the query side of short-query retrieval.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def session_options(threads: int = 1, *, arena: bool = False) -> ort.SessionOptions:
    """One thread, no spinning: onnxruntime sizes its pool from the host's cores and ignores
    the container's CPU quota, so the defaults thrash on a 0.1-CPU instance.

    The CPU memory arena is off by default because it never gives memory back: one batch of
    64 passages grew the process from 140 MB to 395 MB and it stayed there. Offline corpus
    embedding can turn it on for speed.
    """
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.enable_cpu_mem_arena = arena
    opts.enable_mem_pattern = arena
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return opts


class OnnxEncoder:
    """CLS-pooled, L2-normalised embeddings from a BERT-style ONNX graph."""

    def __init__(
        self,
        model_path: Path | str,
        tokenizer_path: Path | str,
        *,
        max_length: int = 512,
        query_prefix: str = "",
        threads: int = 1,
        arena: bool = False,
    ) -> None:
        self.session = ort.InferenceSession(
            str(model_path),
            sess_options=session_options(threads, arena=arena),
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.query_prefix = query_prefix
        self.dim = int(self.session.get_outputs()[0].shape[-1])

    def _run(self, texts: list[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch(texts)
        feeds = {
            "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
        }
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        hidden = self.session.run(None, feeds)[0]  # [batch, seq, dim]
        cls = hidden[:, 0, :]
        return cls / np.linalg.norm(cls, axis=1, keepdims=True).clip(min=1e-12)

    def encode(self, texts: list[str], batch_size: int = 1) -> np.ndarray:
        """Embed passages, one at a time by default, the way queries are embedded.

        The int8 graph quantizes activations with one scale per batch, padding included, so a
        batched passage's vector depended on its batch-mates: renaming one label's chunks and
        rebuilding moved 1,504 of 1,595 vectors (cosine down to 0.995). Batches above 1 are
        sorted by length so padding stays small."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        order = np.argsort([len(t) for t in texts])
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for start in range(0, len(texts), batch_size):
            idx = order[start : start + batch_size]
            out[idx] = self._run([texts[i] for i in idx])
        return out

    def encode_query(self, query: str) -> np.ndarray:
        return self._run([self.query_prefix + query])[0].astype(np.float32)
