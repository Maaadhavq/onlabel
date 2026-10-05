# OnLabel evaluation

Generated 2026-10-05 by `evals/summarize.py` from the JSON in `reports/`. Every number below traces to a committed report, and the model answers behind them are in the committed cache (`cache/llm`), so a fresh clone reproduces them without API keys.

## The benchmark

132 claims written from 63 fact cards across 12 FDA labels (54 faithful, 78 violative). Each card holds verbatim label text; `evals/build_bench.py` refuses to build if any quote is missing from its label. A claim's expected verdict comes from how it was built (restated faithfully, a qualifier dropped, a population broadened, a figure inflated, superiority or an absolute added, a risk denied, a contraindication contradicted, a dose changed), never from a model.

Splits follow the active ingredient. Semaglutide and tirzepatide labels were in view while the prompts and guards were written (dev, 62 claims); the other six ingredients were not (test, 70 claims).

Faithful efficacy claims state the figure with its trial context (study length, population, dose, comparator). A claim that generalises one study's figure to "in clinical trials" is not used as a faithful item, because an MLR reviewer would ask for a qualifier (PROGRESS finding 12).

## Would it trace a violation?

Traced means the reviewer shows the claim as supported. A violative claim that comes back traced is the failure the tool exists to prevent; a faithful claim that is not traced costs a reviewer a look.

| Model | Split | Violative claims traced (guards on) | Guards off | Faithful claims traced | Sent to a human |
|---|---|---|---|---|---|
| gpt-oss-120b (Groq) | test (70) | 2/42 (95% CI 0% to 12%) | 2/42 | 25/28 | 7% |
| Gemma 4 26B (Google AI Studio) | all (132) | 0/78 (95% CI 0% to 5%) | 2/78 | 39/54 | 32% |
| Llama 3.1 8B (local) | all (132) | 3/78 (95% CI 0% to 9%) | 9/78 | 23/54 | 28% |

Intervals are 95% cluster-bootstrap intervals over fact cards (claims written from one card share their evidence); with no violative claim traced, the Wilson interval. Per-claim results: `reports/verify_*.md`.

- Gemma 4 26B (Google AI Studio): the guards stopped 2 violative claims the model had called supported.
- Gemma 4 26B (Google AI Studio): no usable answer for 25 claims, scored as sent to a human (blocked by the provider's filter (content_filter: RECITATION), invalid output: Unterminated string starting at: line 1 column 15 (char 14), InternalServerError 500, invalid output: Expecting ',' delimiter: line 2 column 5317 (char 5693)).
- Llama 3.1 8B (local): the guards stopped 6 violative claims the model had called supported.

## Retrieval

Does the label text a claim depends on reach the judge? Gold is the character span of each card quote, so chunkings of any shape score on the same footing.

| Index | Configuration | Hit@5 | Judge's excerpts | MRR@10 |
|---|---|---|---|---|
| fixed (fixed, 1247 chunks) | dense | 0.70 | 0.86 | 0.47 |
| fixed (fixed, 1247 chunks) | bm25 | 0.80 | 0.89 | 0.48 |
| fixed (fixed, 1247 chunks) | hybrid | 0.89 | 0.93 | 0.57 |
| fixed (fixed, 1247 chunks) | hybrid+figures | 0.86 | 0.93 | 0.58 |
| fixed (fixed, 1247 chunks) | production | 0.88 | 0.92 | 0.48 |
| section (section, 1595 chunks) | dense | 0.85 | 0.93 | 0.59 |
| section (section, 1595 chunks) | bm25 | 0.84 | 0.89 | 0.57 |
| section (section, 1595 chunks) | hybrid | 0.89 | 0.93 | 0.67 |
| section (section, 1595 chunks) | hybrid+figures | 0.86 | 0.91 | 0.67 |
| section (section, 1595 chunks) | production | 0.96 | 0.98 | 0.58 |
| section_batched_embeddings (section, 1595 chunks) | dense | 0.85 | 0.94 | 0.60 |
| section_batched_embeddings (section, 1595 chunks) | bm25 | 0.84 | 0.89 | 0.57 |
| section_batched_embeddings (section, 1595 chunks) | hybrid | 0.89 | 0.95 | 0.68 |
| section_batched_embeddings (section, 1595 chunks) | hybrid+figures | 0.86 | 0.91 | 0.68 |
| section_batched_embeddings (section, 1595 chunks) | production | 0.95 | 0.96 | 0.63 |

`production` is what the API sends the judge: 5 similarity hits plus up to 2 excerpts from the sections that govern the claim's kind, 6 at most. `Judge's excerpts` is hit@10 for the other rows.

## Red team

Each attack wraps a violative claim in an injection asking for it to be traced. The patterns and the attacks were written by the same person, so the pattern layer's hit rate is an upper bound; Prompt Guard 2 is the layer nobody tuned to this set.

| Model | Model alone | + guards | + injection check | Patterns flag attacks | Prompt Guard 2 alone | False alarms on benign copy |
|---|---|---|---|---|---|---|
| gpt-oss-20b (Groq) | 1/17 traced | 0/17 | 0/17 | 15/18 | 3/18 | 0/18 |
| Llama 3.1 8B (local) | 2/18 traced | 2/18 | 0/18 | 15/18 | 3/18 | 0/18 |

## Limits

- One author wrote the cards, the perturbations and the red team. The synthetic set measures whether the pipeline catches violations of known shapes; it is not a sample of real promotional copy.
- The planned holdout of claims FDA cited in 2024-26 untitled letters is not built yet; it needs a person to verify each extracted claim.
- Free-tier daily quotas (Groq: 200K tokens a day per model) limited gpt-oss-120b to the test split, and its red-team run stopped after 4 attacks, so the full red team ran on gpt-oss-20b, the next model in the production chain. The committed cache makes every run repeatable.
- Visuals, audio, layout and a piece's overall impression are out of scope, as the page says.

## Reproduce

```bash
uv run python -m evals.build_bench
uv run python -m evals.retrieval_eval
uv run python -m evals.verify_eval --model groq/gpt-oss-120b --split test
uv run python -m evals.redteam_eval --model groq/gpt-oss-120b
uv run python -m evals.summarize
```
