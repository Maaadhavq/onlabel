# PROGRESS: session handoff

Read this first when resuming. The approved plan is
`C:\Users\madha\.claude\plans\plan-jiggly-galaxy.md` (2026-10-05): ideas, ranking, the
OnLabel build plan, eval design, phases, and the interview kit.

## Current phase

Phase 0 (de-risk), started 2026-10-05.

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
(`onlabel/models.py`, digests match the Hub's LFS metadata).

## Done this session (2026-10-05)

- Repo scaffold: `pyproject.toml` (uv, Python 3.12), `.gitattributes`, `.gitignore`,
  `.env.example`, `onlabel/env.py` (ported from mandate-retry-sequencer).
- `onlabel/retrieval/encoder.py`: torch-free ONNX encoder (CLS pooling, L2 norm, one thread).
- `onlabel/models.py` + `scripts/fetch_models.py`: pinned, hash-checked ONNX artefacts.
- `scripts/probe_runtime.py`: memory and latency probe (native numbers in finding 1).
- `onlabel/llm/registry.py`: every model ID in one place; `scripts/smoke_llm.py` checks
  them against each provider's live model list.
- `Dockerfile` + `.dockerignore`: runtime image (ONNX only).

## Next

1. Probe inside Docker at `--memory=512m --cpus=0.1` (the Render free-tier limits).
2. `smoke_llm.py` against Ollama now, Groq and AI Studio once keys exist.
3. Phase 1 walking skeleton: 3 DailyMed labels, chunks, hybrid retrieval, one grounded
   verdict, `POST /reviews`, minimal page, Render deploy.

## Needs Madhav

- Free API keys in `.env`: `GROQ_API_KEY` (console.groq.com) and `GEMINI_API_KEY`
  (aistudio.google.com).
- GitHub repo `Maaadhavq/onlabel` (empty, public) before the first push.
