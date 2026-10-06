# Claim verification: groq/gpt-oss-120b

Run `gpt-oss-120b_test`, 70 claims (test split). Traced = the reviewer shows the claim as supported. Intervals are 95% cluster-bootstrap intervals over fact cards.

| | Guards on (what the reviewer shows) | Guards off (model verdict) |
|---|---|---|
| False-approval rate (violative claims traced) | 0.00 (0.00-0.00) [0/42] | 0.05 (0.00-0.12) [2/42] |
| Faithful claims traced | 0.89 (0.76-1.00) [25/28] | 1.00 (1.00-1.00) [28/28] |
| Violative claims given an expected verdict | 0.91 | 0.93 |
| Expected violation tag listed | 0.71 | 0.71 |
| Sent to a human | 0.09 | 0.00 |

test: false approvals 0/42, faithful traced 25/28 (guards on).

## By construction (guards on)

| Built as | n | supported | needs qualifier | unsupported | contradicted | off-label | human | expected verdict |
|---|---|---|---|---|---|---|---|---|
| faithful | 28 | 25 | 0 | 0 | 0 | 0 | 3 | 25 |
| drop_qualifier | 6 | 0 | 4 | 0 | 0 | 0 | 2 | 4 |
| broaden | 9 | 0 | 0 | 0 | 5 | 4 | 0 | 9 |
| inflate | 6 | 0 | 0 | 3 | 2 | 0 | 1 | 5 |
| superiority | 4 | 0 | 0 | 3 | 1 | 0 | 0 | 4 |
| deny_risk | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 3 |
| contradict | 7 | 0 | 0 | 0 | 6 | 1 | 0 | 7 |
| wrong_dose | 7 | 0 | 1 | 0 | 6 | 0 | 0 | 6 |

## False approvals (0)

None.

## Model said supported, the guards stopped it (2)

- `victoza-ind-glycemic:1` (drop_qualifier) -> needs_human_review [conditions_not_in_claim:diet and exercise]: VICTOZA improves blood sugar control in adults and children 10 years and older with type 2 diabetes.
- `januvia-ind:1` (drop_qualifier) -> needs_human_review [conditions_not_in_claim:diet and exercise]: JANUVIA improves blood sugar control in adults with type 2 diabetes.

## Faithful claims not traced (3)

- `victoza-comp-glimepiride:0` -> needs_human_review [claim_figures_not_in_quotes:52]: In a 52-week trial in adults with type 2 diabetes, VICTOZA 1.8 mg lowered A1C by 1.1%, compared with 0.5% for glimepiride 8 mg.
- `farxiga-eff:0` -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: In a 24-week trial of FARXIGA alone in adults with type 2 diabetes, A1C fell by 0.9% with FARXIGA 10 mg, compared with 0.2% with placebo.
- `januvia-eff:0` -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: In a 24-week study in adults with type 2 diabetes, A1C fell by 0.6% with JANUVIA 100 mg, while it rose by 0.2% with placebo.

Tokens: 179,326 (2,562 a claim). Live calls 0, cached 70. Median latency 0.01 s a claim.
