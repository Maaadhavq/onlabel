# OnLabel

An MLR pre-check agent. It splits promotional drug copy into claims, traces each claim to
the FDA label, and flags the ones it cannot ground: overstated efficacy, implied
superiority, populations outside the indication, missing risk information. A human
reviewer makes every decision; OnLabel prepares the evidence.

Work in progress. Build log and findings: [PROGRESS.md](PROGRESS.md).

## How a claim is checked (walking skeleton)

1. Hybrid retrieval over DailyMed labels: bge-small int8 embeddings, BM25 that keeps
   figures whole, and reciprocal-rank fusion. Chunks that contain a claim's exact figures
   are always shown to the judge.
2. An open-weight LLM (Groq gpt-oss, AI Studio Gemma, or local Ollama) returns a verdict
   and verbatim quotes as strict JSON.
3. Deterministic guards decide what is reported: a quote must be found in the excerpt it
   cites (no fuzzy matching on figures), and a "supported" verdict must carry every figure
   the claim states. Anything else goes to a human.

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

Open http://localhost:5180. Without API keys, reviews use local Ollama if it is in
`ONLABEL_LLM_CHAIN` (see `.env.example`), otherwise they go straight to human review.

## Rebuild the data

```bash
uv run python -m onlabel.data.fetch_labels
uv run python -m onlabel.retrieval.build_index
```

## Tests and checks

```bash
uv run pytest
uv run ruff check .
uv run python scripts/smoke_deps.py --data
uv run python scripts/smoke_llm.py
```

The runtime image is sized for Render's free tier (512 MB, 0.1 CPU):

```bash
docker build -t onlabel-api .
docker run --rm --memory=512m --cpus=0.1 onlabel-api python scripts/probe_runtime.py
```
