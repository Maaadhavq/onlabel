# Retrieval eval: section

Index `data/index` (section chunks, 1595 of them), 132 benchmark claims. A hit is a chunk overlapping the gold label span. `production` is what the API sends the judge: 5 hits plus up to 2 routed-section excerpts, 6 at most.

| Configuration | hit@1 | hit@3 | hit@5 | hit@10 (production: all) | MRR@10 |
|---|---|---|---|---|---|
| dense | 0.42 | 0.73 | 0.85 | 0.93 | 0.59 |
| dense (no label filter) | 0.42 | 0.73 | 0.85 | 0.93 | 0.59 |
| bm25 | 0.38 | 0.73 | 0.84 | 0.89 | 0.57 |
| bm25 (no label filter) | 0.35 | 0.53 | 0.64 | 0.78 | 0.47 |
| hybrid | 0.51 | 0.81 | 0.89 | 0.93 | 0.67 |
| hybrid (no label filter) | 0.49 | 0.82 | 0.87 | 0.92 | 0.66 |
| hybrid+figures | 0.53 | 0.82 | 0.86 | 0.91 | 0.67 |
| hybrid+figures (no label filter) | 0.52 | 0.78 | 0.85 | 0.90 | 0.66 |
| production | 0.36 | 0.80 | 0.96 | 0.98 | 0.58 |
| production (no label filter) | 0.14 | 0.67 | 0.89 | 0.92 | 0.39 |

95% Wilson intervals are in the JSON. By split (production, label filter on):

- dev: hit@5 0.97, all excerpts 0.98 (n=62)
- test: hit@5 0.96, all excerpts 0.97 (n=70)

Claims whose gold span is not among the judge's excerpts (production): 3

- `januvia-eff:2`
- `mounjaro-comp-semaglutide:1`
- `saxenda-limit:0`
