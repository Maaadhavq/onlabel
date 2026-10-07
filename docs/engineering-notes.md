# Engineering notes

What went wrong while building OnLabel, what each problem showed, and what changed in the
code. Numbers come from the committed reports in `reports/` unless a note says they were
measured during development.

- [Retrieval](#retrieval)
- [The judge and the guards](#the-judge-and-the-guards)
- [Free-tier models](#free-tier-models)
- [Prompt injection](#prompt-injection)
- [Runtime and deployment](#runtime-and-deployment)
- [The benchmark](#the-benchmark)

## Retrieval

### A claim's figure and the label's figure were different tokens

The first end-to-end run called a true claim unsupported: "lost an average of 14.9% ... at
68 weeks". BM25 kept "14.9%" as one token while the label's efficacy table says "-14.9", so
the exact figure never matched. The tokenizer now drops the percent sign and the leading
minus from numbers. (`onlabel/retrieval/bm25.py`)

### Table rows embed badly, so rare figures are pinned

With matching tokens, the table chunk holding -14.9 still ranked below 50 for dense search
and 9th for BM25, and lost the fusion. Chunks that contain a claim's rare figures (document
frequency of 10 or less) are now pinned into the judge's context.
(`onlabel/retrieval/index.py`)

### Similarity search alone did not show the judge the governing section

The first sample reviews had three wrong verdicts. "Ozempic reduces the risk of kidney
failure" was traced because the judge never saw the full Indications wording, which limits
that benefit to adults with type 2 diabetes and chronic kidney disease. "Can be used with a
personal history of MTC" was called a conflict on contraindication text the judge had not
been shown, so the guards sent it to a reviewer. "It lowers A1C" missed every HbA1c table.
Claims are now routed by kind to the sections that govern them (Indications for indication
claims; boxed warning, contraindications and precautions for safety claims), and BM25
treats A1C and HbA1c as the same term. (`onlabel/review.py: SECTION_ROUTES, gather`)

### Routing let the boxed warning crowd out the contraindication

"Do not use WEGOVY with a family history of MTC" never showed the judge the
Contraindications section. The safety route took the two best chunks across all of its
sections, and the thyroid boxed warning won both slots. Routing now takes the best chunk of
each governing section first. A second bug in the same function skipped a governing chunk
that was already the fifth similarity hit, then cut it at the six-excerpt limit. Measured
during development on the dev split: indication claims had their governing text in view
48 of 55 times with similarity search alone, and 55 of 55 times with routing.

### Section-aware chunks matter more than any search setting

With fixed 180-word windows, dense search put the governing label text in the top 5 for 70%
of claims, and the judge's excerpts held it for 92%. Section-aware chunks score 85% and 98%.
(`reports/retrieval_fixed.md`, `reports/retrieval_section.md`)

### int8 embeddings depended on their batch-mates

Renaming one label's chunks and rebuilding the index moved 1,504 of 1,595 vectors (cosine
similarity down to 0.995). Dynamic int8 quantization picks one activation scale per batch,
padding included, and the encoder batched passages sorted by length, so a passage's vector
depended on its neighbours. Passages are now embedded one at a time, like queries. Retrieval
scores barely moved, and index builds became reproducible: one label can change without
moving the rest. (`onlabel/retrieval/encoder.py: OnnxEncoder.encode`)

## The judge and the guards

### A confident wrong answer that the quote check passed

Llama 3.1 8B called the 14.9% claim supported on a verbatim quote of "-14.8", a real number
from a different study, while also listing a violation. The quote was real, so grounding
passed it. Two rules catch this: a supported verdict must carry every figure the claim
states inside its own quotes, and it cannot list violations. The claim went to a reviewer
with both reasons named. (`onlabel/agent/guards.py`)

### Correct verdicts were rejected for how they quoted

gpt-oss-120b correctly called "Wegovy is approved for children as young as 8" off-label,
but it shortened its quote with "..." and also quoted a section title. Both failed
grounding, so a right answer became "reviewer decides". Elided quotes now match when every
fragment appears in order (exact or normalized, never fuzzy, within 800 characters), and the
page shows the located label text in full. Section titles, table captions and table headers
are quotable, and a table's caption or header vouches for a figure its row lacks ("Week
68"). The prompt asks for unshortened quotes. (`onlabel/agent/ground.py`)

### A third of rejected quotes were real quotes, written differently

The first live check of copy that names two drugs sent both claims to a reviewer:
gpt-oss-120b's verdicts were right, but none of its quotes matched the excerpt it cited.
Replaying all 567 quotes in the cached benchmark answers showed the guards had rejected 89.
Of those, 23 flattened a bulleted list into one line ("patients with: - A personal ..."),
10 were word for word in a different excerpt the judge had been shown (two labels carry the
same boxed-warning sentence), 7 cited excerpt ids that do not exist, and several joined a
list's lead-in to a later item or a table caption to a later row.

Grounding now folds inline bullets, superscript marks and "[see ...]" cross-references. It
accepts stitched quotes, whose parts are each found word for word with only whole lines
skipped between them (at most 4 parts within 1,600 characters). It moves a quote to the shown
excerpt it is really in, and it ignores empty quotes. 35 rejections remain, mostly tables a
model rebuilt in its own layout. One loophole closed on the way: figures in a skipped middle
used to count as quoted, and now only the quoted parts vouch for figures.
(`onlabel/agent/ground.py`, `onlabel/agent/guards.py`)

### Every remaining false approval left out a condition of the indication

Regenerating the samples, gpt-oss-120b traced "Ozempic also reduces the risk of kidney
failure" on the indication that limits it to adults with type 2 diabetes and chronic kidney
disease, and restated that limit in its own reasoning. The quote was real and the claim had
no figures, so no guard applied. The benchmark's remaining false approvals were all the same
kind: a glycemic claim without "as an adjunct to diet and exercise", a cardiovascular claim
without "established cardiovascular disease".

A traced claim that rests on Indications text must now carry the conditions of the quoted
item and of the lines that introduce it. A trial result backed by a Clinical Studies quote
is exempt. Replayed over the cached answers, false approvals went from 2 of 42 to 0 of 42
(gpt-oss-120b, test split), from 1 of 78 to 0 of 78 (Gemma 4 26B) and from 3 of 78 to 1 of
78 (Llama 3.1 8B), with no faithful claim held back. The rule was written after seeing
test-split failures, so the test split no longer measures it blind; a holdout of claims FDA
actually cited would. A bug found on the way: a model's "type 2 diabetes" written with a
no-break space read as missing. (`onlabel/agent/guards.py: missing_conditions`)

### Smaller logic errors found in the same review

- Ages and doses under 11 were never compared, so "as young as 8" passed against "12 years
  and older". Small numbers now count when a unit or an age goes with them.
- A suggested rewrite was re-checked against the labels of a few evidence excerpts. Jobs now
  remember the labels their review detected, and the re-check uses those.
- `POST /reviews` without a label judged a claim against all 12 labels. It now detects the
  drug from the claim and answers 422 when it finds none.
- Copy with more than 8 claims said "8 claims found" and skipped the rest without saying so.
  The page now says how many claims were not checked.
- A check waiting behind a running review was given no queue position. The queue counts it
  now.
- A model out of its daily quota was asked again for every claim. The client now rests it
  for as long as the provider says.

## Free-tier models

### Per-minute token limits bind before quality does

Every hosted model passed a strict-JSON smoke test (gpt-oss-120b 2.4 s, gpt-oss-20b 9.3 s,
Qwen3.8-27B 0.5 s, Gemma 4 26B 4.5 s). The third judge call in a minute then got a 429:
each call reserves about 3.6K of Groq's 8K tokens a minute. The client keeps its own
60-second token ledger per model. The live API moves to the next model in the chain when
one is busy, and eval runs wait. Groq's 429 text names the organization, so only the error
type and status code reach the trace. A stalled Gemma call once held a review for 90 s, so
the API's per-call timeout is 30 s. (`onlabel/llm/client.py`)

### Model behaviour worth knowing

- Qwen3.8-27B once returned `{"claims": []}` for a five-claim email. Claim splitting now
  rejects empty or unlocatable answers, asks the next model, and never caches them.
- Gemma 4 on Google's OpenAI-compatible endpoint answers 500 to JSON schemas that use
  `$defs`. Inlined schemas work.
- Llama Prompt Guard 2 on Groq returns a plain probability: 0.0005 for "Ask your doctor...",
  0.9995 for "Ignore all previous instructions...".

### Google's recitation filter blanks verbatim label quotes

Gemma 4 on Google AI Studio returned `finish_reason: content_filter: RECITATION` with an
empty answer, or JSON cut off mid-string, on claims whose evidence is label text quoted word
for word, which is the judge's whole job. The client names the filter in the trace and
retries a length-truncated answer once with twice the token room. A blocked claim goes to a
reviewer, and Gemma stays last in the chain. In the benchmark run, 24 of 132 Gemma answers
were unusable; they are scored as sent to a reviewer. (`reports/verify_gemma-4-26b_all.md`)

### A fallback model traced the claim FDA cited

Regenerating the samples after gpt-oss-120b's daily quota ran out, gpt-oss-20b answered and
traced "Ozempic also reduces the risk of kidney failure"; gpt-oss-120b had said it needs a
qualifier. The fallback chain changes how safe the answers are as well as how fast they
come. The conditions rule above applies to every model's answers. A stricter option would
send every verdict a fallback model traces to a reviewer, at the cost of fewer traced claims
whenever the first model is out of quota.

## Prompt injection

### Prompt Guard misses injections written for this application

On the red-team set, Llama Prompt Guard 2 flagged 3 of 18 attacks: the classic "ignore
previous instructions", including base64-encoded and French versions. Patterns written for
MLR copy flagged 15 of 18. Neither raised a false alarm on 18 benign copy lines. Llama 3.1
8B traced 2 attacks (a fake SYSTEM line and an embedded verdict object). The guards could
not catch them because the quotes were real, and the injection check held both. The
patterns and the attacks share an author, so 15 of 18 is an upper bound.
(`onlabel/safety/injection.py`, `reports/redteam_*.md`)

### Copy that denies a boxed-warning risk passed the risk check

The first live check on Render counted "TRULICITY carries no risk of thyroid tumors" as
mentioning the boxed warning. A denial within four words of the warning's subject now flags
minimized risk. Instructions ("do not use if ...") and uncertainty ("not known whether")
are left alone. (`onlabel/agent/document.py: denials`)

## Runtime and deployment

### ONNX Runtime's CPU memory arena never gives memory back

Natively, one batch of 64 passages grew the process from 140 MB to 395 MB, and it stayed
there. With `enable_cpu_mem_arena=False` and `enable_mem_pattern=False` the same run ends at
144 MB, for slightly slower inference (ten cross-encoder pairs went from 240 ms to 330 ms on
one thread). Runtime sessions keep the arena off; the offline index build turns it on.
(`onlabel/retrieval/encoder.py: session_options`)

### Render's free tier, measured in Docker

At `--memory=512m --cpus=0.1`, a bge-small query takes about 100 ms. The API container is
ready 31 s after a cold start (model load 2.1 s), idles at 130 MiB, and a review's retrieval
takes 172 ms. A MiniLM cross-encoder, measured as a possible reranker, took 0.45 s per
claim-excerpt pair at this CPU share (4.5 s for ten), so the shipped pipeline does not
rerank. (`scripts/probe_runtime.py`)

### The Hugging Face CDN drops long downloads

The first Docker build lost its connection at 12 of 34 MB. `scripts/fetch_models.py`
resumes with HTTP Range requests and checks each file against a pinned SHA-256
(`onlabel/models.py`; the digests match the Hub's LFS metadata). The next build dropped at
12.6 MB and resumed cleanly.

## The benchmark

### "14.9% at 68 weeks" is arguable

gpt-oss-120b judged "in clinical trials, adults lost an average of 14.9%" overstated: -14.9
is the result of one study, while Studies 3 and 4 in the label show -9.6 and -16. An MLR
reviewer would likely ask for a qualifier. Faithful efficacy claims in the benchmark
therefore state the figure with its trial context (study length, population, dose,
comparator), and a claim that generalises one study's figure is never a faithful item.

### Judgement calls the benchmark does not score

The first live check on unseen copy traced "Lose up to 20.9%" (the Zepbound label reports
20.9% for 15 mg), and the Ozempic sample's "may help you lose some weight" is traced the
same way. An MLR reviewer may still object to "up to" or "some". The benchmark has no
efficacy claims worded this way, so its numbers say nothing about them.
