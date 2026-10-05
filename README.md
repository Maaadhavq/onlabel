# OnLabel

An MLR pre-check agent. It splits promotional drug copy into claims, traces each claim to
the FDA label, and flags the ones it cannot ground: overstated efficacy, implied
superiority, populations outside the indication, missing risk information. A human
reviewer makes every decision; OnLabel prepares the evidence.

Work in progress. Build log and findings: [PROGRESS.md](PROGRESS.md).

## Run the checks

```bash
uv sync --extra dev --extra data
uv run python scripts/smoke_deps.py --data
uv run python scripts/fetch_models.py
uv run python scripts/probe_runtime.py
uv run python scripts/smoke_llm.py
```
