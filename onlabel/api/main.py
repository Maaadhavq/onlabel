"""HTTP API for the review pipeline.

Startup binds the port first and loads the index and the ONNX encoder in a background
thread: Render's health check must answer while a 0.1-CPU instance is still reading
models. Until the pipeline is ready, review requests get a 503 that says so.

    uv run uvicorn onlabel.api.main:app --port 8060
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from onlabel.env import load_env
from onlabel.llm.cache import ResponseCache
from onlabel.llm.client import LLMClient
from onlabel.llm.registry import DEMO_CHAIN, MODELS
from onlabel.models import BGE_SMALL_INT8
from onlabel.retrieval.encoder import BGE_QUERY_PREFIX, OnnxEncoder
from onlabel.retrieval.index import LabelIndex
from onlabel.review import DAILYMED_URL, Reviewer

load_env()

INDEX_DIR = Path(os.environ.get("ONLABEL_INDEX_DIR", "data/index"))
MAX_CLAIM_CHARS = 600
REVIEWS_PER_HOUR = int(os.environ.get("ONLABEL_REVIEWS_PER_HOUR", "20"))
# Per model call. A stalled provider once held a review for 90 s before the chain moved on;
# a visitor will not wait that long, and the next model usually answers in 2-10 s.
LLM_TIMEOUT_S = float(os.environ.get("ONLABEL_LLM_TIMEOUT_S", "30"))


class State:
    reviewer: Reviewer | None = None
    index: LabelIndex | None = None
    error: str | None = None
    loaded_in_s: float | None = None
    lock = threading.Lock()  # one review at a time: the instance has a tenth of a CPU


state = State()


def _chain() -> list[str]:
    raw = os.environ.get("ONLABEL_LLM_CHAIN")
    keys = [k.strip() for k in raw.split(",")] if raw else DEMO_CHAIN
    unknown = [k for k in keys if k not in MODELS]
    if unknown:
        raise ValueError(f"ONLABEL_LLM_CHAIN names unknown models: {unknown}")
    return keys


def _load() -> None:
    t = time.perf_counter()
    try:
        index = LabelIndex.load(INDEX_DIR)
        encoder = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path,
                              query_prefix=BGE_QUERY_PREFIX)
        llm = LLMClient(_chain(), ResponseCache(os.environ.get("ONLABEL_CACHE_DIR", "cache/llm")),
                        offline=os.environ.get("ONLABEL_OFFLINE") == "1", timeout_s=LLM_TIMEOUT_S)
        state.index, state.reviewer = index, Reviewer(index, encoder, llm)
        state.loaded_in_s = round(time.perf_counter() - t, 1)
    except Exception as exc:  # noqa: BLE001 - surfaced through /health, not swallowed
        state.error = f"{type(exc).__name__}: {exc}. Run `uv run python scripts/fetch_models.py` " \
                      "and `uv run python -m onlabel.retrieval.build_index` first."


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_load, daemon=True).start()
    yield


app = FastAPI(title="OnLabel", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Exact origins only: a wildcard would let any page spend the free-tier LLM quota.
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5180").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

_recent: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(ip: str) -> None:
    now = time.time()
    q = _recent[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= REVIEWS_PER_HOUR:
        raise HTTPException(429, f"Limit of {REVIEWS_PER_HOUR} reviews per hour reached; the samples still work.")
    q.append(now)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=8, max_length=MAX_CLAIM_CHARS)
    labels: list[str] | None = Field(default=None, max_length=5)


@app.get("/health")
def health() -> dict:
    ready = state.reviewer is not None
    return {
        "status": "ready" if ready else ("error" if state.error else "loading"),
        "error": state.error,
        "loaded_in_s": state.loaded_in_s,
        "chunks": len(state.index.chunks) if state.index else None,
        "llm_chain": _chain(),
    }


@app.get("/labels")
def labels() -> list[dict]:
    if state.index is None:
        raise HTTPException(503, "Still loading the label index; try again in a few seconds.")
    out = []
    for key, entry in state.index.meta.get("labels", {}).items():
        drug = next((c.drug for c in state.index.chunks if c.label_key == key), key.upper())
        out.append({"key": key, "drug": drug, "set_id": entry["set_id"], "version": entry["version"],
                    "url": DAILYMED_URL.format(set_id=entry["set_id"])})
    return out


@app.post("/reviews")
async def review(req: ReviewRequest, request: Request) -> dict:
    if state.reviewer is None:
        raise HTTPException(503, state.error or "Still loading models; try again in a few seconds.")
    known = set(state.index.meta.get("labels", {}))
    if req.labels and not set(req.labels) <= known:
        raise HTTPException(422, f"Unknown labels {sorted(set(req.labels) - known)}; indexed: {sorted(known)}")
    _rate_limit(request.client.host if request.client else "unknown")

    def run() -> dict:
        with state.lock:
            return state.reviewer.review_claim(req.claim, req.labels).to_dict()

    return await anyio.to_thread.run_sync(run)
