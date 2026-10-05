# OnLabel

An MLR pre-check workspace. Paste promotional copy for a prescription drug and OnLabel
finds the claims, checks each one against the FDA label, and shows the label text behind
every verdict: off-label populations, figures the label does not report, benefits stated
without the label's qualifier, risks the copy denies, and boxed warnings the copy leaves
out. A reviewer makes every decision; OnLabel prepares the evidence.

Work in progress. Build log and findings: [PROGRESS.md](PROGRESS.md).

## What happens to a piece of copy

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
   its subject, the page says so first.
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

## Tests and checks

```bash
uv run pytest
uv run ruff check .
uv run python scripts/smoke_llm.py
```

The API image is sized for Render's free tier (512 MB, 0.1 CPU):

```bash
docker build -t onlabel-api .
docker run --rm --memory=512m --cpus=0.1 onlabel-api python scripts/probe_runtime.py
```
