# PROGRESS: session handoff

Read this first when resuming. The approved plan is
`C:\Users\madha\.claude\plans\plan-jiggly-galaxy.md` (2026-10-05): ideas, ranking, the
OnLabel build plan, eval design, phases, and the interview kit.

## Current phase

Phase 1 (walking skeleton) built and verified locally on 2026-10-05. Waiting on Madhav
for the GitHub repo and API keys before the first Render deploy (see "Needs Madhav").

## Findings that change assumptions (READ THESE)

### 1. onnxruntime's CPU memory arena never gives memory back
Natively, bge-small int8 + MiniLM int8 load in 140 MB. One batch of 64 passages grew the
process to 395 MB and it stayed there. With `enable_cpu_mem_arena=False` and
`enable_mem_pattern=False` the same run ends at 144 MB; 10 rerank pairs cost 330 ms instead
of 240 ms (native, 1 thread). Runtime sessions keep the arena off
(`onlabel/retrieval/encoder.py: session_options`).

### 2. Docker Desktop would not start: stale AF_UNIX sockets from July
`starting services: initializing Inference manager ... remove ...\Docker\run\dockerInference:
The file cannot be accessed by the system`, then the same for
`...\docker-secrets-engine\engine.sock`. Windows cannot rename or delete these socket files
directly, but it can rename the folder holding them. Fixed by renaming
`%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` to `*.stale-20261005`
(a second `run.stale-20261005b` holds the socket the crashed start left behind). Nothing was
deleted; the three `.stale` folders hold only dead 0-byte sockets and can go. Engine 29.6.1
came up 10 s after the rename.

### 3. Smart App Control: every runtime dependency loads on Windows
`scripts/smoke_deps.py --data` on Windows Python 3.12.13: fastapi 0.142.2, uvicorn 0.54.0,
pydantic 2.13.5, httpx 0.28.1, openai 3.24.0, numpy 2.5.3, onnxruntime 1.30.0,
tokenizers 0.23.2, pymupdf 1.28.2, huggingface_hub 1.33.0: all OK, no pyarrow or lxml.
So the API and evals run natively (Windows venv via uv); WSL is only for torch training.

### 4. WSL cannot reach the Windows Ollama
WSL is in NAT mode (no `.wslconfig`), and Ollama listens on 127.0.0.1. Anything that calls
Ollama runs on the Windows side. Changing either setting was not needed.

### 5. The Hub CDN drops long downloads
The first Docker build lost the connection at 12 of 34 MB. `scripts/fetch_models.py` now
resumes with Range requests and checks each file against a pinned SHA-256
(`onlabel/models.py`, digests match the Hub's LFS metadata). The rebuild hit a drop at
12.6 MB again and resumed cleanly. Ollama's registry dropped the gemma4:e4b pull the same
way; it is being retried.

### 6. Render limits measured in Docker (`--memory=512m --cpus=0.1`)
Probe: RSS 143 MB with both models loaded, 203 MB after reranking; bge-small query 100 ms;
MiniLM cross-encoder 0.45 s per claim-evidence pair (10 pairs: 4.5 s). The API container
is ready 31 s after a cold start (model load 2.1 s), idles at 130 MiB, and a keyless
review's retrieval takes 172 ms. Budget the verifier at 3-4 windows per claim.

### 7. A claim's figure and the label's figure tokenised differently
First end-to-end run: the true claim "lost an average of 14.9% ... at 68 weeks" came back
unsupported. BM25 kept "14.9%" as one token while the efficacy table says "-14.9", so the
exact-figure match never happened. Numbers now drop % and sign (`retrieval/bm25.py`).

### 8. Table rows embed badly; rare figures are now pinned
Even with the token fix, the table chunk holding -14.9 was dense rank > 50 and BM25 rank
9, and lost the three-way fusion. Chunks containing a claim's rare figures (df <= 10) are
now pinned into the judge's context (`retrieval/index.py`). Table-to-sentence text for
embedding is the next lever; measure it in the Phase 3 ablation.

### 9. Guards caught a confident wrong answer the quote check could not
Llama 3.1 8B then called the 14.9% claim "supported" on a verbatim quote of "-14.8"
(a real number from a different study) while also listing a violation. The quote guard
passes that; two new rules catch it: a supported verdict must carry every claim figure in
its own quotes, and must not list violations (`agent/guards.py`). Result:
needs_human_review with both reasons named. The 8B model is not good enough to confirm
true numeric claims; the hosted models and the verifier have to be measured in Phase 4.

## Done this session (2026-10-05)

- Repo scaffold: `pyproject.toml` (uv, Python 3.12), `.gitattributes`, `.gitignore`,
  `.env.example`, `onlabel/env.py` (ported from mandate-retry-sequencer).
- `onlabel/retrieval/encoder.py`: torch-free ONNX encoder (CLS pooling, L2 norm, one thread).
- `onlabel/models.py` + `scripts/fetch_models.py`: pinned, hash-checked ONNX artefacts.
- `scripts/probe_runtime.py`: memory and latency probe (native numbers in finding 1).
- `onlabel/llm/registry.py`: every model ID in one place; `scripts/smoke_llm.py` checks
  them against each provider's live model list.
- `Dockerfile` + `.dockerignore`: runtime image (ONNX only).

- Phase 1 skeleton: `onlabel/data/` (DailyMed client, SPL parser, chunker, corpus,
  fetcher with manifest), `onlabel/retrieval/` (BM25, index with RRF + figure pinning,
  build script), `onlabel/llm/` (cache, client), `onlabel/agent/` (ground, guards, judge,
  verdict), `onlabel/review.py`, `onlabel/api/main.py`, `web/` (Vite + React page),
  `render.yaml`. 42 tests, ruff clean. Labels: Wegovy v19, Ozempic v20, Mounjaro v40
  (431 chunks). Browser-checked: sample claim -> verdict, grounded quotes, flags, trace.
- Launch entries `onlabel-api` (:8060) and `onlabel-web` (:5180) in
  `Downloads\.claude\launch.json`. Local `.env` routes the chain to Ollama after the
  hosted models and keeps dev answers in `scratch/cache_api`.

## Next

1. First Render deploy (needs the repo), then `smoke_llm.py` against Groq and AI Studio.
2. Phase 2 corpus: the rest of the deep set and comparators, version history, indication
   table, trials snapshot, OPDP letters (Madhav verifies the extracted claims).
3. Phase 3 benchmark and retrieval ablation (span gold, ingredient splits).

## Needs Madhav

- Free API keys in `.env`: `GROQ_API_KEY` (console.groq.com) and `GEMINI_API_KEY`
  (aistudio.google.com).
- GitHub repo `Maaadhavq/onlabel` (empty, public) before the first push.
