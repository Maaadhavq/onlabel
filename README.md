# OnLabel

An MLR pre-check workspace. Paste promotional copy for a prescription drug and OnLabel
finds the claims, checks each one against the FDA label, and shows the label text behind
every verdict: off-label populations, figures the label does not report, benefits stated
without the label's qualifier, risks the copy denies, and boxed warnings the copy leaves
out. A reviewer makes every decision; OnLabel prepares the evidence.

- **Live:** https://onlabel-web.onrender.com (free hosting: the first check after a quiet
  spell waits about 30 seconds for the server; the samples open at once)
- **How it was tested:** https://onlabel-web.onrender.com/#evals and [EVALS.md](EVALS.md)
- **A sample review:** https://onlabel-web.onrender.com/#sample/mounjaro-hcp-detail-aid
- Build log and findings: [PROGRESS.md](PROGRESS.md)

## What happens to a piece of copy

0. **Read the copy as untrusted.** Hidden text is exposed first (zero-width characters, HTML
   comments, invisible elements, base64), then patterns written for MLR copy and Llama Prompt
   Guard 2 look for instructions aimed at the reviewer ("MLR already approved this", "mark it
   as supported"). If they find any, every claim is still checked, and none can be traced.
1. **Find the drug and the claims.** Brand names in the copy pick the DailyMed label. A
   fast open-weight model copies each claim out word for word; a claim it cannot point to
   in the copy is dropped, and if no model answers, sentences become the claims.
2. **Retrieve the evidence.** Hybrid search over the label (bge-small int8 embeddings, BM25
   that keeps figures whole, reciprocal-rank fusion). Chunks holding a claim's exact figures
   are pinned, and every claim also sees the sections that govern it: Indications for
   indication claims, the boxed warning and contraindications for safety claims.
3. **Judge.** An open-weight model (gpt-oss, Qwen or Gemma on free tiers) returns a verdict
   and verbatim quotes as strict JSON. When a model is at its per-minute limit the next one
   answers.
4. **Check the judge.** Plain code decides what is reported: a quote must be found in the
   excerpt it cites (never fuzzily when it holds figures), a "traced" verdict must carry
   every figure the claim states, and a verdict that contradicts itself goes to a human.
5. **Check the whole piece.** If the label has a boxed warning and the copy never mentions
   its subject, or names it only to deny it ("no risk of thyroid tumors"), the page says so
   first.
6. **Suggest on-label wording** on request. The suggestion is checked by the same pipeline;
   the model that wrote it never grades it.

Results stream to the page claim by claim (server-sent events, resumable). Three sample
reviews ship with the page, so it is useful while the free server wakes up.

## Run it locally

```bash
uv sync --extra dev --extra data
uv run python scripts/fetch_models.py
uv run uvicorn onlabel.api.main:app --port 8060
```

```bash
npm --prefix web install
npm --prefix web run dev
```

Open http://localhost:5180. Live checks need `GROQ_API_KEY` and/or `GEMINI_API_KEY` in
`.env` (see `.env.example`); local Ollama models can be added to `ONLABEL_LLM_CHAIN`.

## Rebuild the data and the samples

```bash
uv run python -m onlabel.data.fetch_labels
uv run python -m onlabel.retrieval.build_index
uv run python scripts/make_samples.py
```

## How it was tested

Full results, intervals and every failure: [EVALS.md](EVALS.md), or the page's "How it was
tested" view. Headline numbers:

- **gpt-oss-120b, test split (70 claims from six ingredients nobody looked at while the
  prompts were written):** 2 of 42 violative claims traced (both a blood-sugar claim with
  "as an adjunct to diet and exercise" left out), 25 of 28 faithful claims traced; the other
  3 went to a reviewer because a quote did not match the label table word for word.
- **Llama 3.1 8B, all 132 claims:** the guards cut violative claims traced from 9 to 3 of
  78. They also hold back half of its faithful claims, mostly ones it called supported while
  listing violations or quoting text the label does not contain.
- **Retrieval:** the governing label text is among the judge's excerpts for 129 of 132
  claims (98%) with section-aware chunks, and for 92% with fixed 180-word windows.
- **Red team (18 injection attacks, 18 benign copy lines):** no attack got its claim traced
  with every layer on; the patterns flagged 15 attacks and no benign line, Llama Prompt
  Guard 2 alone flagged 3.

## Run the evaluation

The benchmark is 132 claims written from 63 hand-written fact cards over the 12 labels; each
card's label text is checked word for word before anything runs, and each claim's expected
verdict comes from how it was built. Model answers are in the committed cache (`cache/llm`),
so these reproduce the reports without API keys.

```bash
uv run python -m evals.build_bench
uv run python -m evals.retrieval_eval
uv run python -m evals.verify_eval --model groq/gpt-oss-120b --split test
uv run python -m evals.redteam_eval --model groq/gpt-oss-120b
uv run python -m evals.summarize
```

## Tests and checks

```bash
uv run pytest
uv run ruff check .
npm --prefix web test
uv run python scripts/smoke_llm.py
```

The API image is sized for Render's free tier (512 MB, 0.1 CPU):

```bash
docker build -t onlabel-api .
docker run --rm --memory=512m --cpus=0.1 onlabel-api python scripts/probe_runtime.py
```
