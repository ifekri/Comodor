# Comodor blocked optimization experiment — mimo-v2.5-pro

`xiaomi` · 2026-09-16 · 48 blocks · 336 attempts · Windows 11, Python 3.13.14

Every `(task, try)` block ran all seven configurations in a counterbalanced order, so a CURRENT-vs-ablation pair differs by the switch and little else.

**273/336 attempts passed.**

| Ablation | Cur-only | Abl-only | Both | Neither | mean total delta | median total delta | median ratio | lower/eq/higher |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| dedup | 2 | 1 | 37 | 8 | -1395.9 | -431.0 | 0.9895 | 31/0/17 |
| delta | 1 | 1 | 38 | 8 | -6806.6 | -255.5 | 0.9902 | 27/0/21 |
| budget | 2 | 1 | 37 | 8 | -10391.4 | -247.5 | 0.9901 | 26/0/22 |
| ranking | 1 | 3 | 38 | 6 | -13613.2 | -627.5 | 0.9784 | 32/0/16 |
| summary_provenance | 2 | 1 | 37 | 8 | -3508.0 | -498.5 | 0.9845 | 31/0/17 |
| log_summary | 1 | 2 | 38 | 7 | -7473.1 | -236.5 | 0.9919 | 29/0/19 |

`total_tokens = input + cached + output` (what the model read plus what it wrote; cached is additive, not a subset of input). `cost_usd` is 0.00 for a model with no price mapping — it is not evidence of equal cost.
