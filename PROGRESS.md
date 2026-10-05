# PROGRESS: session handoff

Read this first when resuming. The approved plan is
`C:\Users\madha\.claude\plans\plan-jiggly-galaxy.md` (2026-10-05): ideas, ranking, the
OnLabel build plan, eval design, phases, and the interview kit.

## Current phase

Product UI built (2026-10-05): the React workspace from the Claude Design canvas
(https://claude.ai/artifact/ERqB5PYVKhHwGL645a5YDG), whole-document review streamed over
SSE, claim routing, three stored samples with checked rewrites. Repo is public at
https://github.com/Maaadhavq/onlabel; keys are in Madhav's local `.env`. Madhav asked to
see the UI before the Render deploy, so the deploy waits for his go-ahead.

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

### 10. Free-tier minute limits are the binding constraint, not quality
With keys in place every hosted model passed the strict-JSON smoke test (gpt-oss-120b 2.4 s,
gpt-oss-20b 9.3 s, Qwen3.8-27B 0.5 s, Gemma 4 26B 4.5 s; Prompt Guard 2 returns a plain
probability: 0.0005 for "Ask your doctor...", 0.9995 for "Ignore all previous
instructions..."). The third judge call in a minute then got a 429: each call reserves about
3.6K of Groq's 8K tokens a minute. `LLMClient` now keeps its own 60 s ledger per model; the
live API moves to the next model when one is busy, eval runs wait. Groq's 429 text names the
organization, so only the error type and status code reach the trace. A stalled Gemma call
held one review for 90 s; the API's per-call timeout is now 30 s.

### 11. Correct verdicts were being rejected for how they quoted
gpt-oss-120b called "Wegovy is approved for children as young as 8" off-label (right) but
shortened its quote with "..." and also quoted a section title; both failed grounding, so the
right answer became needs_human_review. Now: elided quotes match if every fragment appears in
order (exact or normalised, never fuzzy; span capped at 800 chars; the UI shows the located
text with the elided middle, never the model's shortened version), titles and table
captions/headers are quotable, and a table's caption/header vouches for figures its row
lacks ("Week 68"). Prompt v2 asks for unshortened quotes. Next run: off_label with an exact
quote.

### 12. Gold labels will need care: "14.9% at 68 weeks" is arguable
gpt-oss-120b judged the claim overstated: -14.9 is Study 2's result while Studies 3 and 4
show -9.6 and -16, so "in clinical trials, adults lost an average of 14.9%" generalises one
study. An MLR reviewer would likely ask for a qualifier. The benchmark must define its labels
(and accept needs_qualifier) before any accuracy number means anything.

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

### 13. Similarity search alone does not show the judge the governing section
The first samples had three wrong verdicts. "Ozempic reduces the risk of kidney failure" was
traced although the label limits it to adults with type 2 diabetes and CKD (the judge never
saw the full Indications wording); "can be used with a personal history of MTC" was called
a conflict on contraindication text the judge was never shown, so the guard rightly sent it
to a human; "It lowers A1C" missed every HbA1c table. Fixes: claims are routed by kind to
the sections that govern them (`review.py: SECTION_ROUTES`, 2 routed excerpts, 6 max), and
an A1C/HbA1c query synonym (`retrieval/bm25.py`).

### 13b. First live check on unseen copy (Zepbound, 2026-10-05)
Through the page, against the twelve-label index (1,595 chunks): label detected from the
brand, 4 claims in 6.5 s and 9,892 tokens. Teen use off-label, "works better than any other
weight-loss medicine" not in the label, diet and activity traced, missing boxed-warning
risk information flagged. "Lose up to 20.9%" was traced (the label reports 20.9% for 15 mg);
an MLR reviewer may still object to "up to". The Ozempic sample's "may help you lose some
weight" is traced the same way. Both are judgement calls the benchmark has to define.

### 14. Free-tier model behaviour worth knowing
Qwen3.8-27B once returned `{"claims": []}` for a five-claim email; `accept=` now rejects
empty or unlocatable answers and asks the next model, never caching them. Gemma 4 on Google's
OpenAI-compatible endpoint answers 500 to schemas with `$defs`, fine once inlined (11.5 s).
In eval mode every call goes to the first model and waits: about 30 calls take 15 minutes.

## Earlier in-flight notes (2026-10-05, stopped at the usage limit; items 1-5 now done)

Product UI work, from the Claude Design canvas https://claude.ai/artifact/ERqB5PYVKhHwGL645a5YDG
(Review workspace + First visit / Server waking up / Checking, live). Backend for it is built
and tested (71 tests): `agent/document.py` (claim split, label detection, risk-information
check), `agent/evidence.py`, `agent/rewrite.py`, `api/jobs.py`, `/documents` + SSE events +
rewrite endpoints. A live run of the Wegovy spring email streamed all 6 claims in 70 s.
Done just now: `$ref`-inlined strict schemas (Gemma 4 answered 500 with `$defs`, works
inlined: 11.5 s), token estimate len/3.5 and the ledger settled to real usage.

Left, in order:
1. `LLMClient.complete_json(accept=...)`: reject an empty or unlocatable answer, try the next
   model, never cache it (Qwen once returned `{"claims": []}`, the split fell back to
   sentences and checked a tagline as a claim). Delete `scratch/cache_api` after.
2. `data/chunk.py::_units`: captions render as "- Table 8. ..."; strip "- " before the
   "table" check, then rebuild the index (the 14.9% claim needs "Week 68" from the caption).
3. Reviewer `k=5`; add `groq/qwen3.8-27b` to ONLABEL_LLM_CHAIN in Madhav's `.env` (edit the
   line with a script, never print the file: it holds his keys).
4. `scripts/make_samples.py`: 3 sample documents (Wegovy email, Ozempic banner, Mounjaro HCP
   detail aid) -> `web/src/samples/*.json`.
5. React workspace from the design (Public Sans / Source Serif 4 / IBM Plex Mono, highlighter
   evidence, boxed-warning box, claims bar, tabs: evidence / checks / how it decided,
   rewrite on demand, SSE with polling fallback, the three states).
6. Commit, push, then the Render deploy (Madhav asked to see the UI first).

## Next

1. First Render deploy (needs the repo), then `smoke_llm.py` against Groq and AI Studio.
2. Phase 2 corpus: the rest of the deep set and comparators, version history, indication
   table, trials snapshot, OPDP letters (Madhav verifies the extracted claims).
3. Phase 3 benchmark and retrieval ablation (span gold, ingredient splits).

## Needs Madhav

- Free API keys in `.env`: `GROQ_API_KEY` (console.groq.com) and `GEMINI_API_KEY`
  (aistudio.google.com).
- GitHub repo `Maaadhavq/onlabel` (empty, public) before the first push.
