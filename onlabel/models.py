"""The ONNX artefacts the API ships, pinned to exact Hub revisions and SHA-256 digests.

Both are int8 and small enough for a 512 MB / 0.1 CPU instance. Documents and queries are
embedded with the same file; switching the encoder means re-embedding the corpus.
The digests match the Hub's LFS metadata (checked 2026-10-05), so a truncated or
tampered download fails the build instead of loading.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path("models/hf")


@dataclass(frozen=True)
class OnnxArtefact:
    key: str
    repo: str
    revision: str
    onnx_file: str
    onnx_sha256: str
    tokenizer_sha256: str
    tokenizer_file: str = "tokenizer.json"

    @property
    def local_dir(self) -> Path:
        return MODELS_DIR / self.key

    @property
    def onnx_path(self) -> Path:
        return self.local_dir / Path(self.onnx_file).name

    @property
    def tokenizer_path(self) -> Path:
        return self.local_dir / "tokenizer.json"

    def files(self) -> list[tuple[str, Path, str]]:
        """(remote path, local path, sha256) for each file."""
        return [
            (self.onnx_file, self.onnx_path, self.onnx_sha256),
            (self.tokenizer_file, self.tokenizer_path, self.tokenizer_sha256),
        ]


BERT_UNCASED_TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"

BGE_SMALL_INT8 = OnnxArtefact(
    key="bge-small-en-v1.5-int8",
    repo="Xenova/bge-small-en-v1.5",
    revision="ea104dacec62c0de699686887e3f920caeb4f3e3",
    onnx_file="onnx/model_int8.onnx",
    onnx_sha256="bf64d05457cb391fa88d045faf5927a15ea36d96228ddf23ea970087afdc1197",
    tokenizer_sha256=BERT_UNCASED_TOKENIZER_SHA256,
)

# quint8_avx2 rather than avx512: Render's free instances are not guaranteed AVX-512.
MINILM_RERANK_INT8 = OnnxArtefact(
    key="ms-marco-MiniLM-L6-v2-int8",
    repo="cross-encoder/ms-marco-MiniLM-L6-v2",
    revision="233902d25c440f23af6f7d6e94d2946bac0bee0a",
    onnx_file="onnx/model_quint8_avx2.onnx",
    onnx_sha256="c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9",
    tokenizer_sha256=BERT_UNCASED_TOKENIZER_SHA256,
)

SHIPPED = [BGE_SMALL_INT8, MINILM_RERANK_INT8]
