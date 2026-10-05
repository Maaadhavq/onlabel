"""HTTP API for the review pipeline.

Startup binds the port first and loads the index and the ONNX encoder in a background
thread: Render's health check must answer while a 0.1-CPU instance is still reading
models. Until the pipeline is ready, review requests get a 503 that says so.

Whole documents are reviewed as background jobs whose events stream to the page
(`/documents/{id}/events`, server-sent events, resumable with Last-Event-ID).

    uv run uvicorn onlabel.api.main:app --port 8060
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from onlabel.agent.rewrite import suggest_rewrite
from onlabel.api.jobs import Job, JobRunner
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
MAX_DOCUMENT_CHARS = 4000
REVIEWS_PER_HOUR = int(os.environ.get("ONLABEL_REVIEWS_PER_HOUR", "20"))
# Per model call. A stalled provider once held a review for 90 s before the chain moved on;
# a visitor will not wait that long, and the next model usually answers in 2-10 s.
LLM_TIMEOUT_S = float(os.environ.get("ONLABEL_LLM_TIMEOUT_S", "30"))
# Claim splitting is a short, easy call: the fastest models go first.
SPLIT_CHAIN = ["groq/qwen3.8-27b", "groq/gpt-oss-20b", "gemini/gemma-4-26b"]
KEEPALIVE_S = 15


class State:
    reviewer: Reviewer | None = None
    index: LabelIndex | None = None
    runner: JobRunner | None = None
    error: str | None = None
    loaded_in_s: float | None = None
    lock = threading.Lock()  # one review at a time: the instance has a tenth of a CPU


state = State()


def _chain(var: str, default: list[str]) -> list[str]:
    raw = os.environ.get(var)
    keys = [k.strip() for k in raw.split(",") if k.strip()] if raw else default
    unknown = [k for k in keys if k not in MODELS]
    if unknown:
        raise ValueError(f"{var} names unknown models: {unknown}")
    return keys


def _run_document(job: Job) -> None:
    with state.lock:
        state.reviewer.review_document(job.text, job.labels, job.emit)


def _load() -> None:
    t = time.perf_counter()
    try:
        index = LabelIndex.load(INDEX_DIR)
        encoder = OnnxEncoder(BGE_SMALL_INT8.onnx_path, BGE_SMALL_INT8.tokenizer_path,
                              query_prefix=BGE_QUERY_PREFIX)
        cache = ResponseCache(os.environ.get("ONLABEL_CACHE_DIR", "cache/llm"))
        offline = os.environ.get("ONLABEL_OFFLINE") == "1"
        llm = LLMClient(_chain("ONLABEL_LLM_CHAIN", DEMO_CHAIN), cache, offline=offline, timeout_s=LLM_TIMEOUT_S)
        splitter = LLMClient(_chain("ONLABEL_SPLIT_CHAIN", SPLIT_CHAIN), cache, offline=offline,
                             timeout_s=LLM_TIMEOUT_S, budget=llm.budget)
        state.index = index
        state.reviewer = Reviewer(index, encoder, llm, splitter=splitter)
        state.runner = JobRunner(_run_document)
        state.loaded_in_s = round(time.perf_counter() - t, 1)
    except Exception as exc:  # noqa: BLE001 - surfaced through /health, not swallowed
        state.error = f"{type(exc).__name__}: {exc}. Run `uv run python scripts/fetch_models.py` " \
                      "and `uv run python -m onlabel.retrieval.build_index` first."


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_load, daemon=True).start()
    yield


app = FastAPI(title="OnLabel", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Exact origins only: a wildcard would let any page spend the free-tier LLM quota.
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5180").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)

_recent: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(ip: str, cost: int = 1) -> None:
    now = time.time()
    q = _recent[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) + cost > REVIEWS_PER_HOUR:
        raise HTTPException(429, f"Limit of {REVIEWS_PER_HOUR} checks an hour reached. The samples still open.")
    q.extend([now] * cost)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ready() -> Reviewer:
    if state.reviewer is None:
        raise HTTPException(503, state.error or "Still loading models; try again in a few seconds.")
    return state.reviewer


def _known_labels(labels: list[str] | None) -> None:
    known = set(state.index.meta.get("labels", {}))
    if labels and not set(labels) <= known:
        raise HTTPException(422, f"Unknown labels {sorted(set(labels) - known)}; indexed: {sorted(known)}")


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=8, max_length=MAX_CLAIM_CHARS)
    labels: list[str] | None = Field(default=None, max_length=5)


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=MAX_DOCUMENT_CHARS)
    label: str | None = None  # None: detect from the copy
    audience: Literal["consumer", "hcp"] = "consumer"


@app.get("/health")
def health() -> dict:
    ready = state.reviewer is not None
    return {
        "status": "ready" if ready else ("error" if state.error else "loading"),
        "error": state.error,
        "loaded_in_s": state.loaded_in_s,
        "chunks": len(state.index.chunks) if state.index else None,
        "llm_chain": _chain("ONLABEL_LLM_CHAIN", DEMO_CHAIN),
    }


@app.get("/labels")
def labels() -> list[dict]:
    if state.index is None:
        raise HTTPException(503, "Still loading the label index; try again in a few seconds.")
    out = []
    for key, meta in state.index.meta.get("labels", {}).items():
        out.append({"key": key, "drug": (meta.get("products") or [key.upper()])[0], "set_id": meta["set_id"],
                    "version": meta["version"], "effective_time": meta.get("effective_time"),
                    "url": DAILYMED_URL.format(set_id=meta["set_id"])})
    return out


@app.post("/reviews")
async def review(req: ReviewRequest, request: Request) -> dict:
    reviewer = _ready()
    _known_labels(req.labels)
    _rate_limit(_ip(request))

    def run() -> dict:
        with state.lock:
            return reviewer.review_claim(req.claim, req.labels).to_dict()

    return await anyio.to_thread.run_sync(run)


@app.post("/documents", status_code=202)
def create_document(req: DocumentRequest, request: Request) -> dict:
    _ready()
    labels = [req.label] if req.label else None
    _known_labels(labels)
    _rate_limit(_ip(request))
    job = state.runner.submit(Job(req.text, labels, req.audience))
    return {"id": job.id, "events": f"/documents/{job.id}/events"}


def _job(job_id: str) -> Job:
    job = state.runner.get(job_id) if state.runner else None
    if job is None:
        raise HTTPException(404, "No such review. It may have expired; run the check again.")
    return job


@app.get("/documents/{job_id}")
def document(job_id: str) -> dict:
    job = _job(job_id)
    events, done = job.since(0)
    return {"id": job.id, "done": done, "events": events}


@app.get("/documents/{job_id}/events")
async def document_events(job_id: str, request: Request) -> StreamingResponse:
    job = _job(job_id)
    try:
        start = int(request.headers.get("last-event-id", "-1")) + 1
    except ValueError:
        start = 0

    async def stream():
        i, quiet_since = start, time.monotonic()
        while True:
            events, done = job.since(i)
            for ev in events:
                yield f"id: {ev['id']}\nevent: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
                i = ev["id"] + 1
                quiet_since = time.monotonic()
            if done and not job.since(i)[0]:
                return
            if time.monotonic() - quiet_since > KEEPALIVE_S:
                yield ": still checking\n\n"
                quiet_since = time.monotonic()
            if await request.is_disconnected():
                return
            await anyio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/documents/{job_id}/claims/{n}/rewrite")
async def rewrite(job_id: str, n: int, request: Request) -> dict:
    reviewer = _ready()
    job = _job(job_id)
    original = job.claim_review(n)
    if original is None:
        raise HTTPException(409, "That claim has not been checked yet.")
    if original["status"] == "supported":
        raise HTTPException(409, "That claim already traces to the label.")
    _rate_limit(_ip(request))
    chunks = [c for c in (reviewer.index.get(e["chunk_id"]) for e in original["evidence"]) if c]
    chunks += [c for c in (reviewer.index.get(r["chunk_id"]) for r in original["retrieved"][:3]) if c and c not in chunks]

    def run() -> dict:
        with state.lock:
            res = suggest_rewrite(reviewer.llm, original["claim"], original, chunks, job.audience)
            if res.data is None:
                raise HTTPException(503, "No model is available to suggest wording right now. Try again in a minute.")
            labels = sorted({c.label_key for c in chunks}) or job.labels
            check = reviewer.review_claim(res.data.rewrite, labels, kind=job.claim_kind(n))
            return {"rewrite": res.data.rewrite, "model": res.model_key, "review": check.to_dict()}

    return await anyio.to_thread.run_sync(run)
