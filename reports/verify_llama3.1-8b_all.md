# Claim verification: ollama/llama3.1-8b

Run `llama3.1-8b_all`, 132 claims (all split). Traced = the reviewer shows the claim as supported. Intervals are 95% cluster-bootstrap intervals over fact cards.

| | Guards on (what the reviewer shows) | Guards off (model verdict) |
|---|---|---|
| False-approval rate (violative claims traced) | 0.01 (0.00-0.04) [1/78] | 0.12 (0.05-0.19) [9/78] |
| Faithful claims traced | 0.44 (0.31-0.58) [24/54] | 0.89 (0.80-0.96) [48/54] |
| Violative claims given an expected verdict | 0.81 | 0.83 |
| Expected violation tag listed | 0.32 | 0.32 |
| Sent to a human | 0.27 | 0.00 |

dev: false approvals 1/36, faithful traced 13/26 (guards on).

test: false approvals 0/42, faithful traced 11/28 (guards on).

## By construction (guards on)

| Built as | n | supported | needs qualifier | unsupported | contradicted | off-label | human | expected verdict |
|---|---|---|---|---|---|---|---|---|
| faithful | 54 | 24 | 2 | 4 | 0 | 0 | 24 | 24 |
| drop_qualifier | 15 | 1 | 5 | 1 | 0 | 2 | 6 | 8 |
| broaden | 16 | 0 | 0 | 9 | 3 | 4 | 0 | 16 |
| inflate | 11 | 0 | 1 | 6 | 1 | 0 | 3 | 7 |
| superiority | 8 | 0 | 0 | 8 | 0 | 0 | 0 | 8 |
| absolute | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| deny_risk | 6 | 0 | 0 | 3 | 3 | 0 | 0 | 6 |
| contradict | 9 | 0 | 0 | 3 | 5 | 0 | 1 | 8 |
| wrong_dose | 12 | 0 | 1 | 7 | 2 | 0 | 2 | 9 |

## False approvals (1)

- `wegovy-ind-weight:1` (drop_qualifier): WEGOVY injection helps adults and children 12 years and older with obesity lose excess weight and keep it off long term.

## Model said supported, the guards stopped it (8)

- `wegovy-eff-tablets:1` (inflate) -> needs_human_review [claim_figures_not_in_quotes:19.6,2.4]: In a 64-week study of adults with obesity, or overweight with a weight-related condition, people taking WEGOVY 25 mg tablets lost an average of 19.6% of their body weight, compared with 2.4% with placebo.
- `ozempic-ind-glycemic:1` (drop_qualifier) -> needs_human_review [supported_but_lists_violations, conditions_not_in_claim:diet and exercise]: OZEMPIC improves blood sugar control in adults with type 2 diabetes.
- `rybelsus-ind-cv:1` (drop_qualifier) -> needs_human_review [conditions_not_in_claim:established cardiovascular disease or high cardiovascular risk]: RYBELSUS reduces the risk of heart attack and stroke in adults with type 2 diabetes.
- `victoza-ind-glycemic:1` (drop_qualifier) -> needs_human_review [quote_reattributed, supported_but_lists_violations, conditions_not_in_claim:diet and exercise]: VICTOZA improves blood sugar control in adults and children 10 years and older with type 2 diabetes.
- `victoza-ind-cv:1` (drop_qualifier) -> needs_human_review [quote_reattributed, quote_reattributed, supported_but_lists_violations]: VICTOZA reduces the risk of heart attack and stroke in adults with type 2 diabetes.
- `trulicity-ind-cv:1` (drop_qualifier) -> needs_human_review [conditions_not_in_claim:established cardiovascular disease or high cardiovascular risk]: TRULICITY reduces the risk of heart attack and stroke in adults with type 2 diabetes.
- `jardiance-eff-cv:1` (inflate) -> needs_human_review [claim_figures_not_in_quotes:1.7]: In a cardiovascular outcomes trial in adults with type 2 diabetes and atherosclerotic cardiovascular disease, 1.7% of patients taking JARDIANCE died of cardiovascular causes, compared with 5.9% taking placebo.
- `januvia-ind:1` (drop_qualifier) -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: JANUVIA improves blood sugar control in adults with type 2 diabetes.

## Faithful claims not traced (30)

- `wegovy-ind-cv:0` -> needs_human_review [supported_but_lists_violations]: Along with a reduced-calorie diet and increased physical activity, WEGOVY injection reduces the risk of cardiovascular death, heart attack and stroke in adults with established cardiovascular disease and either obesity or overweight.
- `wegovy-box:0` -> needs_qualifier [quote_reattributed]: In studies in rodents, semaglutide caused thyroid C-cell tumors, and it is unknown whether WEGOVY causes these tumors, including medullary thyroid carcinoma, in humans.
- `wegovy-contra:0` -> needs_human_review [supported_but_lists_violations]: Do not use WEGOVY if you or a family member have ever had medullary thyroid carcinoma (MTC), or if you have Multiple Endocrine Neoplasia syndrome type 2 (MEN 2).
- `wegovy-dose:0` -> needs_human_review [supported_but_lists_violations]: WEGOVY injection starts at 0.25 mg, given once weekly.
- `ozempic-comp-sitagliptin:0` -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: In a 56-week trial in adults with type 2 diabetes also taking metformin and/or a thiazolidinedione, OZEMPIC 1 mg lowered A1C by 1.5%, compared with 0.7% for sitagliptin.
- `ozempic-dose:0` -> needs_human_review [supported_but_lists_violations]: OZEMPIC is taken once a week, on the same day each week, at any time of day, with or without meals.
- `rybelsus-ind-cv:0` -> needs_human_review [supported_but_lists_violations]: RYBELSUS reduces the risk of cardiovascular death, heart attack and stroke in adults with type 2 diabetes who are at high risk for these events.
- `rybelsus-eff-mono:0` -> unsupported: In a 26-week trial of semaglutide tablets alone in adults with type 2 diabetes not controlled by diet and exercise, A1C fell by 1.4% with the 14 mg tablet, compared with 0.3% with placebo.
- `rybelsus-dose:0` -> needs_human_review [supported_but_lists_violations]: Take one RYBELSUS tablet once daily on an empty stomach in the morning, with up to 4 ounces of water.
- `mounjaro-comp-semaglutide:0` -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: In a 40-week trial in adults with type 2 diabetes taking metformin, MOUNJARO 15 mg lowered A1C by 2.3%, compared with 1.9% for semaglutide 1 mg.
- `mounjaro-dose:0` -> needs_human_review [supported_but_lists_violations]: MOUNJARO starts at 2.5 mg, injected once weekly.
- `zepbound-ind-osa:0` -> needs_qualifier [quote_reattributed, quote_reattributed]: With a reduced-calorie diet and increased physical activity, ZEPBOUND treats moderate to severe obstructive sleep apnea in adults with obesity.
- `zepbound-eff:0` -> needs_human_review [quote_not_found_in_excerpt, claim_figures_not_in_quotes:20.9,3.1]: In a 72-week study of adults with obesity or overweight, people taking ZEPBOUND 15 mg lost an average of 20.9% of their body weight, compared with 3.1% with placebo.
- `victoza-ind-glycemic:0` -> needs_human_review [supported_but_lists_violations]: Along with diet and exercise, VICTOZA improves blood sugar control in adults and children 10 years and older with type 2 diabetes.
- `victoza-comp-glimepiride:0` -> unsupported [quote_reattributed]: In a 52-week trial in adults with type 2 diabetes, VICTOZA 1.8 mg lowered A1C by 1.1%, compared with 0.5% for glimepiride 8 mg.
- `victoza-contra:0` -> needs_human_review [supported_but_lists_violations]: VICTOZA should not be used by people with a personal or family history of medullary thyroid carcinoma or with Multiple Endocrine Neoplasia syndrome type 2.
- `saxenda-eff:0` -> unsupported [quote_not_found_in_excerpt]: In a 56-week study of adults with obesity, or overweight with a weight-related condition, people taking SAXENDA lost an average of 7.4% of their body weight, compared with 3% with placebo.
- `saxenda-dose:0` -> needs_human_review [supported_without_grounded_quote]: SAXENDA is injected once daily at any time of day, regardless of when you eat.
- `trulicity-ind-glycemic:0` -> needs_human_review [supported_but_lists_violations]: Along with diet and exercise, TRULICITY improves blood sugar control in adults and children 10 years and older with type 2 diabetes.
- `trulicity-comp-metformin:0` -> needs_human_review [claim_figures_not_in_quotes:1.5]: In a 26-week trial in adults with type 2 diabetes, TRULICITY 1.5 mg lowered A1C by 0.8%, compared with 0.6% for metformin.
- `jardiance-ind-hf:0` -> needs_human_review [supported_but_lists_violations]: JARDIANCE reduces the risk of cardiovascular death and hospitalization for heart failure in adults with heart failure.
- `jardiance-eff-cv:0` -> needs_human_review [supported_but_lists_violations]: In a cardiovascular outcomes trial in adults with type 2 diabetes and atherosclerotic cardiovascular disease, 3.7% of patients taking JARDIANCE died of cardiovascular causes, compared with 5.9% taking placebo.
- `jardiance-dose:0` -> needs_human_review [supported_but_lists_violations]: JARDIANCE is taken as 10 mg once daily in the morning, with or without food.
- `farxiga-eff:0` -> needs_human_review [claim_figures_not_in_quotes:10,24]: In a 24-week trial of FARXIGA alone in adults with type 2 diabetes, A1C fell by 0.9% with FARXIGA 10 mg, compared with 0.2% with placebo.
- `januvia-eff:0` -> needs_human_review [quote_not_found_in_excerpt, supported_without_grounded_quote]: In a 24-week study in adults with type 2 diabetes, A1C fell by 0.6% with JANUVIA 100 mg, while it rose by 0.2% with placebo.
- `januvia-dose:0` -> needs_human_review [supported_but_lists_violations]: The recommended dose of JANUVIA is 100 mg once daily.
- `lantus-contra:0` -> needs_human_review [supported_but_lists_violations]: Do not use LANTUS during episodes of low blood sugar (hypoglycemia).
- `lantus-hypo:0` -> unsupported: Low blood sugar (hypoglycemia) is the most common side effect of insulins, including LANTUS.
- `lantus-comp-nph:0` -> needs_human_review [quote_not_found_in_excerpt, quote_not_found_in_excerpt, quote_not_found_in_excerpt, claim_figures_not_in_quotes:0.4,0.5,52, supported_but_lists_violations]: In a 52-week study in adults with type 2 diabetes taking oral medicines, A1C fell by 0.5% with LANTUS and by 0.4% with NPH insulin.
- `lantus-dose:0` -> needs_human_review [supported_but_lists_violations]: LANTUS is injected once daily, at any time of day but at the same time every day.

Tokens: 301,136 (2,281 a claim). Live calls 0, cached 132. Median latency 0.01 s a claim.
