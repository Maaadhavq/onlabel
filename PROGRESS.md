# PROGRESS: session handoff

Read this first when resuming. The approved plan is
`C:\Users\madha\.claude\plans\plan-jiggly-galaxy.md` (2026-10-05): ideas, ranking, the
OnLabel build plan, eval design, phases, and the interview kit.

## Current phase

Deployed and measured (2026-10-05). Live: https://onlabel-web.onrender.com (page) and
https://onlabel-api.onrender.com (API, Render free, Singapore). Repo:
https://github.com/Maaadhavq/onlabel. GROQ_API_KEY and GEMINI_API_KEY are set in Render
(onlabel-api, Environment) since 2026-10-06.

Phase 3 benchmark built and run: `evals/` (fact cards, retrieval eval, claim verification,
red team, summary). Results: `EVALS.md` and the page's "How it was tested" view (#evals),
both generated from `reports/*.json`.

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

### 15. int8 embeddings depended on their batch-mates
Renaming one label's chunks and rebuilding moved 1,504 of 1,595 vectors (cosine down to
0.995): dynamic int8 quantisation picks one activation scale per batch, padding included, and
the encoder batched passages sorted by length. Passages are now embedded one at a time, like
queries, so a vector depends only on its text. Retrieval quality was unchanged (both indexes
score 0.98 of claims with their label text in front of the judge), but builds are now
reproducible and a single label can change without moving the rest.

### 16. Routing let the boxed warning crowd out the contraindication
Measured on the benchmark's dev split: "Do not use WEGOVY with a family history of MTC" never
showed the judge the Contraindications section, because the safety route took the top two
chunks across boxed warning, contraindications and precautions, and the thyroid sections won
both slots. Routing now takes the best chunk of each governing section first. A second bug in
the same code skipped a governing chunk that was the fifth similarity hit, then cut it at the
six-excerpt limit. Indication claims: 48/55 with similarity alone, 55/55 with routing.

### 17. Google's recitation filter blanks verbatim label quotes
Gemma 4 on Google AI Studio returned `finish_reason: content_filter: RECITATION` with an empty
answer, or a JSON answer cut off mid-string, on claims whose evidence is label text quoted
word for word, which is the judge's whole job. The client now names the filter in the trace,
retries a length-truncated answer with twice the room instead of "repairing" it, and the
reviewer sends a blocked claim to a human. Gemma stays last in the chain.

### 18. Prompt Guard misses injections written for this application
On the red-team set Llama Prompt Guard 2 flagged 3 of 18 attacks (the classic "ignore previous
instructions", including decoded base64 and the French one); patterns written for MLR copy
flagged 15 of 18, with no false alarm on 18 benign copy lines for either. Llama 3.1 8B traced
2 attacks (a fake SYSTEM line, an embedded verdict object); the guards could not catch them
because the quotes were real, and the injection check held both. The patterns and attacks share
an author, so 15/18 is an upper bound.

### 19. Section-aware chunks matter more than any search setting
Fixed 180-word windows: 0.70 of claims with their label text in the top 5 for dense search
and 0.92 in what the judge sees, against 0.85 and 0.98 for section chunks.

### 20. Copy that denies a boxed-warning risk passed the risk check
The first live check on Render: "TRULICITY carries no risk of thyroid tumors" counted as
mentioning the boxed warning. A denial within four words of the warning's subject now flags
minimized risk ("do not use if..." and "not known whether" are not denials).

### 21. The fallback model traced the claim FDA cited
Regenerating the samples after gpt-oss-120b's daily quota ran out, gpt-oss-20b answered and
traced "Ozempic also reduces the risk of kidney failure", which the label limits to adults
with type 2 diabetes and chronic kidney disease (gpt-oss-120b: needs a qualifier). The 120b
sample was kept (the 20b output is in `scratch/`). The fallback chain changes safety, not
only speed. Open decision for Madhav: send every verdict a fallback model traces to a
reviewer, at the cost of fewer traced claims whenever the first model is out of quota.

### 22. A third of rejected quotes were real quotes, written differently
The first live two-label check sent both claims to a reviewer: gpt-oss-120b's verdicts were
right, but none of its quotes matched the excerpt it cited. Replaying all 567 quotes in the
cached benchmark answers, the guards had rejected 89: 23 flattened a bulleted list into one
line ("patients with: - A personal ..."), 10 were found word for word in a different excerpt
the judge was shown (two labels carry the same boxed-warning sentence), 7 cited ids that do
not exist, and several stitched a list's lead-in to a later item or a table caption to a later
row. Grounding now folds inline bullets, superscripts and "[see ...]" cross-references, accepts
"stitched" quotes (parts found word for word with only whole lines skipped, never fuzzy),
moves a quote to the shown excerpt it is really in, and ignores empty quotes: 35 rejections
remain, mostly tables a model rebuilt in its own layout. One loophole closed on the way:
figures in a skipped middle used to count as quoted; now only the quoted parts vouch.

### 23. Smaller logic errors found in the same review
- Ages and doses under 11 were never checked ("as young as 8" passed on "12 years and
  older"); small numbers now count when a unit or an age goes with them.
- A suggested rewrite was re-checked against the labels of a few evidence excerpts, not the
  labels the review used; jobs now remember the labels they detected.
- `/reviews` with no label judged a claim against all 12 labels; it now detects the drug.
- Copy with more than 8 claims said "8 claims found" and silently skipped the rest; the page
  now says how many were not checked.
- The two-label note said each claim "was checked against each" label; it is one judgement
  over both labels' text, and the note says so.
- A new check waiting behind a running review was told nothing; the queue counts it now.
- A model out of its daily quota was asked again for every claim and answered 429 each time;
  the client rests it for as long as the provider says.

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

## Done 2026-10-05 to 06 (deploy, benchmark, safety)

- Render: `onlabel-api` (Docker, free, Singapore) and `onlabel-web` (static). Deploys are
  manual: the repo is connected by URL, so pushes send Render no webhook. Trigger them with
  the Render connector after pushing.
- `onlabel/safety/injection.py` and its place in `review.py`; Prompt Guard 2 wired into the
  API when a Groq key is set (`/health` reports it). 94 Python tests, 9 front-end tests.
- `evals/`: fact cards, benchmark builder, retrieval, verification and red-team evals,
  summary. Reports in `reports/`, model answers in `cache/llm`, results in `EVALS.md` and the
  page's #evals view. Runs: gpt-oss-120b on the test split, Llama 3.1 8B and Gemma 4 26B on
  all claims, red team on gpt-oss-20b and Llama 3.1 8B.
- Page: "How it was tested" (#evals), deep links to samples (#sample/<id>), a fourth sample
  whose email hides an instruction in an HTML comment, injection banner and trace step.

## Next

1. Keys are set on Render (2026-10-06; /health shows prompt_guard true). The two-label quote
   problem from the first live check is fixed (finding 22).
2. OPDP holdout (Set C): 15-20 letters from 2024-26, claims extracted with help, verified by
   Madhav, sealed, run once on the frozen config.
3. When gpt-oss-120b's daily quota resets: the dev split, the rest of the red team, and
   `scripts/make_samples.py` so the three original samples pick up the new index, routing and
   injection fields (they were kept at their 120b versions; see finding 21).
4. LoRA verifier study (plan Phase 5) if time allows; the LLM judge plus guards is the
   shipped path.

## Needs Madhav

- About 10 hours of labelling for the OPDP holdout, and a 15% audit of the benchmark cards.
