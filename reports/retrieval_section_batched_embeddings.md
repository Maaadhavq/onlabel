# Retrieval eval: section_batched_embeddings

Index `scratch/index_batched` (section chunks, 1595 of them), 132 benchmark claims. A hit is a chunk overlapping the gold label span. `production` is what the API sends the judge: 5 hits plus up to 2 routed-section excerpts, 6 at most.

| Configuration | hit@1 | hit@3 | hit@5 | hit@10 (production: all) | MRR@10 |
|---|---|---|---|---|---|
| dense | 0.43 | 0.73 | 0.85 | 0.94 | 0.60 |
| dense (no label filter) | 0.43 | 0.73 | 0.85 | 0.94 | 0.60 |
| bm25 | 0.38 | 0.73 | 0.84 | 0.89 | 0.57 |
| bm25 (no label filter) | 0.35 | 0.53 | 0.64 | 0.78 | 0.47 |
| hybrid | 0.53 | 0.82 | 0.89 | 0.95 | 0.68 |
| hybrid (no label filter) | 0.53 | 0.83 | 0.88 | 0.91 | 0.68 |
| hybrid+figures | 0.54 | 0.82 | 0.86 | 0.91 | 0.68 |
| hybrid+figures (no label filter) | 0.53 | 0.78 | 0.86 | 0.90 | 0.67 |
| production | 0.43 | 0.83 | 0.95 | 0.96 | 0.63 |
| production (no label filter) | 0.27 | 0.77 | 0.91 | 0.94 | 0.51 |

95% Wilson intervals are in the JSON. By split (production, label filter on):

- dev: hit@5 0.94, all excerpts 0.97 (n=62)
- test: hit@5 0.96, all excerpts 0.96 (n=70)

Claims whose gold span is not among the judge's excerpts (production): 7

- `januvia-eff:2`
- `lantus-contra:1`
- `mounjaro-comp-semaglutide:1`
- `mounjaro-contra:1`
- `saxenda-limit:0`
- `wegovy-contra:0`
- `zepbound-box:0`
