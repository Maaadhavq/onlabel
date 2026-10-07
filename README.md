# OnLabel

[![CI](https://github.com/Maaadhavq/onlabel/actions/workflows/ci.yml/badge.svg)](https://github.com/Maaadhavq/onlabel/actions/workflows/ci.yml)

OnLabel checks promotional copy for a prescription drug against the drug's FDA label. It
finds each claim, retrieves the label text that governs it, has an open-weight model judge
it, and shows the exact label sentence behind every verdict. Plain-code checks decide what
is reported, and a reviewer makes every decision.

**[Live demo](https://onlabel-web.onrender.com)** ·
**[How it was tested](https://onlabel-web.onrender.com/#evals)** ·
**[Evaluation report](EVALS.md)** ·
**[Engineering notes](docs/engineering-notes.md)**

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/review-dark.webp">
  <img src="docs/images/review.webp" width="1280" alt="OnLabel reviewing the Ozempic web banner sample: three claims underlined in the copy, the first marked not in the label, with the label's Indications text highlighted as evidence and a notice that the boxed-warning risk information is missing">
</picture>

## Background

Every promotional piece for a prescription drug (emails, web banners, detail aids for
doctors) goes through medical, legal and regulatory (MLR) review before it is used.
Reviewers check by hand that each claim traces to the FDA label: whether a figure appears in
the label, whether the population is on-label, whether the claim keeps the qualifier the
label attaches, and whether the copy plays down a boxed warning. FDA's untitled and warning
letters about drug promotion cite these same problems. OnLabel prepares that evidence before
a reviewer looks.

## What it reports

Each claim gets one of six verdicts. The examples are claims from the app's samples, which
are synthetic test copy.

| Verdict | Example claim | Why |
|---|---|---|
| Traced to label | "Use it with a reduced-calorie diet and increased physical activity." | The label: "Administer WEGOVY in combination with a reduced-calorie diet and increased physical activity." |
| Needs a qualifier | "ZEPBOUND helps adults with obesity lose excess weight and keep it off." | The label attaches a reduced-calorie diet and increased physical activity. |
| Not in the label | "...people taking ZEPBOUND 15 mg lost an average of 25.9% of their body weight." | The label reports 20.9% for the 15 mg dose. |
| Conflicts with label | "MOUNJARO can be used in patients with a personal history of medullary thyroid carcinoma." | That history is a contraindication. |
| Off-label | "Wegovy is approved for weight loss in children as young as 8." | The label covers pediatric patients 12 years and older. |
| Reviewer decides | "Ozempic also reduces the risk of kidney failure." | The model traced it, and a plain-code check held it back: the label limits this benefit to adults with type 2 diabetes and chronic kidney disease. |

For the whole piece, OnLabel also flags a boxed warning the copy leaves out, a boxed-warning
risk the copy denies ("no risk of thyroid tumors"), and instructions aimed at the reviewer.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/injection-dark.webp">
    <img src="docs/images/injection.webp" width="560" alt="OnLabel reviewing a Zepbound email whose HTML comment tells the reviewer to approve every claim: the page leads with a notice that the copy contains instructions aimed at the reviewer">
  </picture>
  <br>
  <sub>The Zepbound sample hides an instruction to the reviewer in an HTML comment. The page leads with it, and no claim in the piece can be traced.</sub>
</p>

## How it works

1. **Read the copy as untrusted input.** Hidden text is exposed first: zero-width
   characters, HTML comments, invisible elements and base64. Patterns written for MLR copy
   and Llama Prompt Guard 2 then look for instructions aimed at the reviewer, such as "MLR
   already approved this" or "mark it as supported". When either finds one, every claim is
   still checked, and none can be traced.
2. **Find the drug and the claims.** Brand names in the copy pick the DailyMed label. A fast
   open-weight model copies each claim out word for word. A claim it cannot point to in the
   copy is dropped, and when no model answers, sentences become the claims.
3. **Retrieve the evidence.** Hybrid search over the label: bge-small int8 embeddings on
   ONNX Runtime, BM25 with a tokenizer that keeps figures whole, and reciprocal-rank fusion.
   Chunks that hold a claim's rare figures are pinned, and each claim also sees the sections
   that govern its kind: Indications for indication claims; the boxed warning,
   contraindications and precautions for safety claims.
4. **Judge.** An open-weight model returns a verdict, violation types in FDA's wording, and
   verbatim quotes as strict JSON. The chain runs gpt-oss-120b, gpt-oss-20b and Qwen3.8-27B
   on Groq, then Gemma 4 26B on Google AI Studio. When a model is at its per-minute limit,
   the next one answers.
5. **Check the judge.** Plain code decides what is reported. Every quote must be found in
   the label text the judge was shown, and a quote that holds a figure must match exactly. A
   traced verdict must carry every figure the claim states and every condition its quoted
   indication attaches, and a verdict that contradicts itself goes to a reviewer.
6. **Check the whole piece.** If the label has a boxed warning and the copy never mentions
   its subject, or names it only to deny it, the page says so first.
7. **Suggest on-label wording** when the reviewer asks. The suggestion goes through the same
   pipeline, and the model that wrote it never grades it.

Results stream to the page claim by claim over server-sent events, and a dropped connection
resumes where it stopped. The reviewer agrees with or changes each verdict and downloads the
review as a JSON audit file.

## Results

From a benchmark of 132 claims written from 63 fact cards across 12 FDA labels: 54 restate
the label faithfully and 78 break it in a known way. Code checks every card's label text
word for word, and each claim's expected verdict comes from how it was built. Full tables,
confidence intervals and every failure are in [EVALS.md](EVALS.md).

| Measure | Result |
|---|---|
| Violative claims traced, gpt-oss-120b, held-out test split | **0 of 42** with the guards; 2 on the model's own verdicts |
| Faithful claims traced, same run | **25 of 28**; the other 3 went to a reviewer |
| Violative claims traced, Gemma 4 26B, all claims | **0 of 78** with the guards; 2 without |
| Violative claims traced, Llama 3.1 8B, all claims | **1 of 78** with the guards; 9 without |
| Governing label text among the judge's excerpts | **98%** with section-aware chunks; 92% with fixed 180-word windows |
| Injection attacks that got their claim traced | **0 of 18**, with no false alarm on 18 benign copy lines |

The test split's 70 claims come from six active ingredients that were kept out of view
while the prompts and guards were written. Two guard rules were written after seeing
benchmark failures, test split included, so the test split no longer measures those rules
blind; the figures without the guards show what each model did on its own.

## Tech stack

| Layer | Tools |
|---|---|
| API | Python 3.12, FastAPI, Pydantic, server-sent events |
| Retrieval | bge-small-en-v1.5 (int8) on ONNX Runtime; BM25 and rank fusion in NumPy |
| Models | gpt-oss-120b, gpt-oss-20b and Qwen3.8-27B on Groq; Gemma 4 26B on Google AI Studio; Llama Prompt Guard 2; Ollama for local runs |
| Frontend | React 19, Vite |
| Infrastructure | Docker, Render free tier (512 MB RAM, 0.1 CPU), GitHub Actions |

## Run it locally

You need Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
git clone https://github.com/Maaadhavq/onlabel.git
cd onlabel
uv sync --extra dev
uv run python scripts/fetch_models.py
uv run uvicorn onlabel.api.main:app --port 8060
```

In a second terminal:

```bash
npm --prefix web install
npm --prefix web run dev
```

Open http://localhost:5180. The samples work with no keys. Checking new copy needs
`GROQ_API_KEY` or `GEMINI_API_KEY` (both have free tiers); copy `.env.example` to `.env` and
fill them in.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | unset | gpt-oss, Qwen and Prompt Guard 2 on Groq |
| `GEMINI_API_KEY` | unset | Gemma 4 on Google AI Studio |
| `ONLABEL_LLM_CHAIN` | the four hosted models | Judge models, tried in order (local Ollama models can be added) |
| `ONLABEL_SPLIT_CHAIN` | Qwen3.8-27B, gpt-oss-20b, Gemma 4 | Claim-splitting models, tried in order |
| `ONLABEL_OFFLINE` | unset | `1` answers from the committed answer cache only |
| `ONLABEL_REVIEWS_PER_HOUR` | `20` | Checks allowed per IP address per hour |
| `ONLABEL_CHECKS_PER_DAY` | `300` | Checks allowed per day across all visitors |
| `CORS_ORIGINS` | `http://localhost:5180` | Origins allowed to call the API |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434/v1` | Local models for bulk evaluation |

To rebuild the corpus and the samples from DailyMed:

```bash
uv run python -m onlabel.data.fetch_labels --all
uv run python -m onlabel.retrieval.build_index
uv run python scripts/make_samples.py
```

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/documents` | Starts a review of a piece of copy and returns its id |
| `GET` | `/documents/{id}/events` | Streams the review as server-sent events; resumes with `Last-Event-ID` |
| `GET` | `/documents/{id}` | Returns the review so far, for clients that poll |
| `POST` | `/documents/{id}/claims/{n}/rewrite` | Suggests on-label wording for claim `n` and checks it |
| `POST` | `/reviews` | Checks a single claim |
| `GET` | `/labels` | Lists the indexed labels and their versions |
| `GET` | `/health` | Reports readiness, the model chain and whether Prompt Guard 2 is on |

## Evaluation

Every model answer behind the reports is committed in `cache/llm`, so the numbers reproduce
without API keys. The red-team runs also call Prompt Guard 2, which needs `GROQ_API_KEY`.

```bash
uv run python -m evals.build_bench
uv run python -m evals.retrieval_eval
uv run python -m evals.verify_eval --model groq/gpt-oss-120b --split test --offline
uv run python -m evals.redteam_eval --model groq/gpt-oss-20b
uv run python -m evals.summarize
```

`evals/summarize.py` writes `EVALS.md` and the data behind the page's "How it was tested"
view. The [full list of runs](EVALS.md#reproduce) covers every committed report.

## Tests

```bash
uv run pytest
uv run ruff check .
npm --prefix web test
```

CI runs all three on every push with no network access, no keys and no model downloads.
Two scripts check the parts CI cannot reach:

```bash
uv run python scripts/smoke_llm.py
docker build -t onlabel-api . && docker run --rm --memory=512m --cpus=0.1 onlabel-api python scripts/probe_runtime.py
```

The first confirms that every configured model ID still exists and answers strict JSON. The
second measures memory and latency inside the API image at Render's free-tier limits.

## Project structure

```
onlabel/
  agent/        claim splitting, the judge, quote grounding, guards, whole-piece checks, rewrites
  api/          FastAPI app and the background job runner
  data/         DailyMed client, SPL parser, chunking
  llm/          model registry, client with fallback and token budgets, answer cache
  retrieval/    ONNX encoder, BM25, hybrid index, index builder
  safety/       injection check
  review.py     the pipeline for one claim and for a whole piece of copy
evals/          benchmark builder and the retrieval, verification and red-team evals
data/           parsed labels (labels/) and the built index the API serves (index/)
cache/llm/      model answers the reports were built from
reports/        per-run results behind EVALS.md
scripts/        model download, sample generation, model check, runtime probe
web/            React workspace
tests/          API, pipeline, grounding, guard and retrieval tests
docs/           engineering notes and images
```

## Deployment

`render.yaml` defines both services: the API as a Docker web service and the page as a
static site. The API image downloads its pinned, hash-checked ONNX encoder at build time and
ships the committed index. API keys are set in the Render dashboard and never reach the page
bundle. The repository is connected by URL, so pushes do not deploy; deploys are started
from Render.

## Limitations

- One author wrote the fact cards, the claims and the red-team attacks. The benchmark
  measures whether violations of known shapes are caught; how often real copy contains them
  is outside what it can show.
- A holdout of claims FDA cited in its 2024-26 untitled letters is not built yet. Each
  extracted claim needs a person to verify it, and it is the blind test the guard rules
  have not had.
- Text only: visuals, audio, layout and a piece's overall impression are out of scope.
- Free-tier quotas set the pace. Groq allows 8K tokens a minute per model, and after a quiet
  spell the free server takes about 30 seconds to start.

## Next steps

- Run the FDA-letter holdout once on the frozen configuration.
- Fine-tune a small verifier (LoRA and full fine-tuning on the same data) to cut LLM calls
  per claim.
- Add video ad scripts as a format.

## Data and disclaimer

Labels come from [DailyMed](https://dailymed.nlm.nih.gov/dailymed/) (U.S. National Library of
Medicine). `data/labels/manifest.json` pins each label's set id, version and XML hash. The
sample copy in the app was written for testing and is marked as synthetic; drug names are
trademarks of their owners. OnLabel is a portfolio project. It prepares evidence for a
reviewer and gives no medical, legal or regulatory advice.

## License

The code is released under the [MIT License](LICENSE). Label text in `data/` comes from
DailyMed, as described above.
