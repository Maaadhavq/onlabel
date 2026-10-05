# Retrieval eval: fixed

Index `scratch/index_fixed` (fixed chunks, 1247 of them), 132 benchmark claims. A hit is a chunk overlapping the gold label span. `production` is what the API sends the judge: 5 hits plus up to 2 routed-section excerpts, 6 at most.

| Configuration | hit@1 | hit@3 | hit@5 | hit@10 (production: all) | MRR@10 |
|---|---|---|---|---|---|
| dense | 0.29 | 0.58 | 0.70 | 0.86 | 0.47 |
| dense (no label filter) | 0.29 | 0.58 | 0.70 | 0.86 | 0.47 |
| bm25 | 0.28 | 0.64 | 0.80 | 0.89 | 0.48 |
| bm25 (no label filter) | 0.27 | 0.46 | 0.56 | 0.70 | 0.39 |
| hybrid | 0.34 | 0.77 | 0.89 | 0.93 | 0.57 |
| hybrid (no label filter) | 0.34 | 0.77 | 0.89 | 0.93 | 0.57 |
| hybrid+figures | 0.37 | 0.77 | 0.86 | 0.93 | 0.58 |
| hybrid+figures (no label filter) | 0.37 | 0.74 | 0.84 | 0.92 | 0.57 |
| production | 0.25 | 0.70 | 0.88 | 0.92 | 0.48 |
| production (no label filter) | 0.12 | 0.48 | 0.84 | 0.92 | 0.35 |

95% Wilson intervals are in the JSON. By split (production, label filter on):

- dev: hit@5 0.90, all excerpts 0.94 (n=62)
- test: hit@5 0.86, all excerpts 0.91 (n=70)

Claims whose gold span is not among the judge's excerpts (production): 10

- `farxiga-dose:1`
- `lantus-contra:0`
- `lantus-contra:1`
- `mounjaro-comp-semaglutide:1`
- `trulicity-ind-cv:2`
- `trulicity-ind-glycemic:1`
- `victoza-dose:1`
- `wegovy-ind-weight:0`
- `wegovy-ind-weight:1`
- `wegovy-ind-weight:2`
