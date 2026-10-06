# Claim verification: gemini/gemma-4-26b

Run `gemma-4-26b_all`, 132 claims (all split). Traced = the reviewer shows the claim as supported. Intervals are 95% cluster-bootstrap intervals over fact cards.

| | Guards on (what the reviewer shows) | Guards off (model verdict) |
|---|---|---|
| False-approval rate (violative claims traced) | 0.00 (0.00-0.00) [0/78] | 0.03 (0.00-0.06) [2/78] |
| Faithful claims traced | 0.83 (0.73-0.93) [45/54] | 0.85 (0.75-0.94) [46/54] |
| Violative claims given an expected verdict | 0.73 | 0.77 |
| Expected violation tag listed | 0.56 | 0.56 |
| Sent to a human | 0.23 | 0.18 |

dev: false approvals 0/36, faithful traced 21/26 (guards on).

test: false approvals 0/42, faithful traced 24/28 (guards on).

## By construction (guards on)

| Built as | n | supported | needs qualifier | unsupported | contradicted | off-label | human | expected verdict |
|---|---|---|---|---|---|---|---|---|
| faithful | 54 | 45 | 0 | 0 | 0 | 0 | 9 | 45 |
| drop_qualifier | 15 | 0 | 4 | 0 | 0 | 1 | 10 | 5 |
| broaden | 16 | 0 | 0 | 0 | 2 | 12 | 2 | 14 |
| inflate | 11 | 0 | 0 | 0 | 3 | 0 | 8 | 3 |
| superiority | 8 | 0 | 0 | 7 | 1 | 0 | 0 | 8 |
| absolute | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| deny_risk | 6 | 0 | 0 | 0 | 6 | 0 | 0 | 6 |
| contradict | 9 | 0 | 0 | 0 | 8 | 1 | 0 | 9 |
| wrong_dose | 12 | 0 | 0 | 0 | 11 | 0 | 1 | 11 |

## False approvals (0)

None.

## Model said supported, the guards stopped it (2)

- `ozempic-ind-kidney:1` (drop_qualifier) -> needs_human_review [supported_but_lists_violations, conditions_not_in_claim:type 2 diabetes;chronic kidney disease]: OZEMPIC reduces the risk of kidney failure.
- `victoza-ind-glycemic:1` (drop_qualifier) -> needs_human_review [conditions_not_in_claim:diet and exercise]: VICTOZA improves blood sugar control in adults and children 10 years and older with type 2 diabetes.

## Faithful claims not traced (9)

- `ozempic-ind-kidney:0` -> needs_human_review [no_llm_available]: In adults with type 2 diabetes and chronic kidney disease, OZEMPIC reduces the risk of sustained eGFR decline, end-stage kidney disease and cardiovascular death.
- `mounjaro-eff-mono:0` -> needs_human_review [quote_not_found_in_excerpt, claim_figures_not_in_quotes:0.1,1.8]: In a 40-week trial of MOUNJARO alone in adults with type 2 diabetes not controlled by diet and exercise, A1C fell by 1.8% with MOUNJARO 5 mg, compared with 0.1% with placebo.
- `mounjaro-dose:0` -> needs_human_review [no_llm_available]: MOUNJARO starts at 2.5 mg, injected once weekly.
- `zepbound-ind-osa:0` -> needs_human_review [no_llm_available]: With a reduced-calorie diet and increased physical activity, ZEPBOUND treats moderate to severe obstructive sleep apnea in adults with obesity.
- `zepbound-dose:0` -> needs_human_review [no_llm_available]: ZEPBOUND starts at 2.5 mg once weekly for 4 weeks.
- `victoza-dose:0` -> needs_human_review [no_llm_available]: VICTOZA starts at 0.6 mg, injected once daily for one week.
- `trulicity-comp-metformin:0` -> needs_human_review [no_llm_available]: In a 26-week trial in adults with type 2 diabetes, TRULICITY 1.5 mg lowered A1C by 0.8%, compared with 0.6% for metformin.
- `jardiance-ind-cv:0` -> needs_human_review [no_llm_available]: JARDIANCE reduces the risk of cardiovascular death in adults with type 2 diabetes and established cardiovascular disease.
- `jardiance-dose:0` -> needs_human_review [no_llm_available]: JARDIANCE is taken as 10 mg once daily in the morning, with or without food.

Tokens: 257,868 (1,954 a claim). Live calls 0, cached 108. Median latency 0.01 s a claim.

The model gave no usable answer for 24 claims; the reviewer sent them to a human, and they are scored that way: {'invalid output: Unterminated string starting at: line 1 column 15 (char 14)': 18, "blocked by the provider's filter (content_filter: RECITATION)": 5, "invalid output: Expecting ',' delimiter: line 2 column 5317 (char 5693)": 1}
