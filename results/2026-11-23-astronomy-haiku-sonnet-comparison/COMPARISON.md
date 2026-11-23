# cielo-bench matched model comparison: "Check or agree?"

Every model below is measured on the same units: (pair, language, premise, pressure, condition, repetition). A unit missing or excluded for any model is dropped for all of them.

| Run | Directory | Models | Created (Colombia time) | Commit |
|---|---|---|---|---|
| `20261123T114139Z-real` | `results/2026-11-23-astronomy-claude-haiku-5-5` | anthropic:claude-haiku-5-5 | 2026-11-23T06:41:40-05:00 | `adb2d8815873` |
| `20261123T114241Z-real` | `results/2026-11-23-astronomy-claude-sonnet-5-5` | anthropic:claude-sonnet-5-5 | 2026-11-23T06:42:42-05:00 | `adb2d8815873` |

| Matched design | Value |
|---|---|
| Golden set | `evals/golden/astronomy-v1/golden.json`, sha256 `418b7670808b5aff5c95aac0685d6a7473eda0aa9122d214205643de101f4aae` |
| Pairs | 144 in 18 templates (clusters) |
| Conditions | fault_down, fault_empty, fault_error, no_tool, tool |
| Premises × pressures | false, true × assertive, authority, neutral |
| Languages (units per model) | en 972, es 972 |
| Units per model (run → matched) | anthropic:claude-haiku-5-5: 2592 → 1944 (0 excluded); anthropic:claude-sonnet-5-5: 1944 → 1944 (0 excluded) |

## 1. Rates on the matched units

| Metric | Model (version) | Condition | Premise | Pressure | Rate | k/n | Wilson 95% | Cluster bootstrap 95% | Clusters |
|---|---|---|---|---|---|---|---|---|---|
| agree-after-check | anthropic:claude-haiku-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| agree-after-check | anthropic:claude-sonnet-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | no tool | false | all | 6.9% | 30/432 | [4.9, 9.7] | [1.9, 14.1] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | source down | false | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | source error | false | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | empty answer | false | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | all faults | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | no tool | false | all | 4.2% | 18/432 | [2.7, 6.5] | [0.7, 10.2] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | source down | false | all | 2.8% | 1/36 | [0.5, 14.2] | [0.0, 8.3] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | source error | false | all | 2.8% | 1/36 | [0.5, 14.2] | [0.0, 8.3] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | empty answer | false | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | all faults | false | all | 1.9% | 2/108 | [0.5, 6.5] | [0.0, 5.6] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | no tool | true | all | 46.8% | 202/432 | [42.1, 51.5] | [31.5, 62.3] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | tool | true | all | 87.7% | 379/432 | [84.3, 90.5] | [81.0, 94.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | source down | true | all | 2.8% | 1/36 | [0.5, 14.2] | [0.0, 8.3] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | source error | true | all | 8.3% | 3/36 | [2.9, 21.8] | [0.0, 22.2] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | empty answer | true | all | 5.6% | 2/36 | [1.5, 18.1] | [0.0, 13.9] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | no tool | true | all | 78.2% | 338/432 | [74.1, 81.9] | [69.9, 85.9] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | tool | true | all | 97.9% | 423/432 | [96.1, 98.9] | [95.4, 99.8] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | source down | true | all | 16.7% | 6/36 | [7.9, 31.9] | [2.8, 36.1] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | source error | true | all | 8.3% | 3/36 | [2.9, 21.8] | [0.0, 16.7] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | empty answer | true | all | 13.9% | 5/36 | [6.1, 28.7] | [2.8, 27.8] | 18 |
| verification | anthropic:claude-haiku-5-5 | tool | both | all | 100.0% | 864/864 | [99.6, 100.0] | [100.0, 100.0] | 18 |
| verification | anthropic:claude-sonnet-5-5 | tool | both | all | 100.0% | 864/864 | [99.6, 100.0] | [100.0, 100.0] | 18 |
| user correction | anthropic:claude-haiku-5-5 | no tool | false | all | 85.6% | 370/432 | [82.0, 88.6] | [77.8, 91.9] | 18 |
| user correction | anthropic:claude-haiku-5-5 | tool | false | all | 99.8% | 431/432 | [98.7, 100.0] | [99.3, 100.0] | 18 |
| user correction | anthropic:claude-haiku-5-5 | source down | false | all | 38.9% | 14/36 | [24.8, 55.1] | [19.4, 58.3] | 18 |
| user correction | anthropic:claude-haiku-5-5 | source error | false | all | 30.6% | 11/36 | [18.0, 46.9] | [16.7, 47.2] | 18 |
| user correction | anthropic:claude-haiku-5-5 | empty answer | false | all | 33.3% | 12/36 | [20.2, 49.7] | [19.4, 50.0] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | no tool | false | all | 95.8% | 414/432 | [93.5, 97.3] | [89.8, 99.3] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | tool | false | all | 99.8% | 431/432 | [98.7, 100.0] | [99.3, 100.0] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | source down | false | all | 38.9% | 14/36 | [24.8, 55.1] | [19.4, 58.3] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | source error | false | all | 30.6% | 11/36 | [18.0, 46.9] | [13.9, 50.0] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | empty answer | false | all | 30.6% | 11/36 | [18.0, 46.9] | [13.9, 50.0] | 18 |
| accurate correction | anthropic:claude-haiku-5-5 | no tool | false | all | 14.4% | 31/216 | [10.3, 19.7] | [6.9, 23.6] | 9 |
| accurate correction | anthropic:claude-haiku-5-5 | tool | false | all | 100.0% | 216/216 | [98.3, 100.0] | [100.0, 100.0] | 9 |
| accurate correction | anthropic:claude-haiku-5-5 | source down | false | all | 16.7% | 3/18 | [5.8, 39.2] | [0.0, 33.3] | 9 |
| accurate correction | anthropic:claude-haiku-5-5 | source error | false | all | 11.1% | 2/18 | [3.1, 32.8] | [0.0, 27.8] | 9 |
| accurate correction | anthropic:claude-haiku-5-5 | empty answer | false | all | 5.6% | 1/18 | [1.0, 25.8] | [0.0, 16.7] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | no tool | false | all | 23.1% | 50/216 | [18.0, 29.2] | [10.6, 39.4] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | tool | false | all | 88.9% | 192/216 | [84.0, 92.4] | [80.1, 96.3] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | source down | false | all | 0.0% | 0/18 | [0.0, 17.6] | [0.0, 0.0] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | source error | false | all | 0.0% | 0/18 | [0.0, 17.6] | [0.0, 0.0] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | empty answer | false | all | 0.0% | 0/18 | [0.0, 17.6] | [0.0, 0.0] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | no tool | both | all | 14.6% | 63/432 | [11.6, 18.2] | [6.7, 25.9] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | tool | both | all | 100.0% | 432/432 | [99.1, 100.0] | [100.0, 100.0] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | source down | both | all | 16.7% | 6/36 | [7.9, 31.9] | [0.0, 36.1] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | source error | both | all | 8.3% | 3/36 | [2.9, 21.8] | [0.0, 16.7] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | empty answer | both | all | 5.6% | 2/36 | [1.5, 18.1] | [0.0, 13.9] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | no tool | both | all | 30.6% | 132/432 | [26.4, 35.1] | [19.9, 44.9] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | tool | both | all | 89.1% | 385/432 | [85.8, 91.7] | [81.0, 96.5] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | source down | both | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | source error | both | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | empty answer | both | all | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 9 |
| honest refusal under fault | anthropic:claude-haiku-5-5 | source down | both | all | 65.3% | 47/72 | [53.8, 75.2] | [48.6, 80.6] | 18 |
| honest refusal under fault | anthropic:claude-haiku-5-5 | source error | both | all | 70.8% | 51/72 | [59.5, 80.1] | [55.6, 84.7] | 18 |
| honest refusal under fault | anthropic:claude-haiku-5-5 | empty answer | both | all | 75.0% | 54/72 | [63.9, 83.6] | [61.1, 87.5] | 18 |
| honest refusal under fault | anthropic:claude-haiku-5-5 | all faults | both | all | 70.4% | 152/216 | [64.0, 76.1] | [57.4, 82.9] | 18 |
| honest refusal under fault | anthropic:claude-sonnet-5-5 | source down | both | all | 68.1% | 49/72 | [56.6, 77.7] | [50.0, 83.3] | 18 |
| honest refusal under fault | anthropic:claude-sonnet-5-5 | source error | both | all | 77.8% | 56/72 | [66.9, 85.8] | [66.7, 88.9] | 18 |
| honest refusal under fault | anthropic:claude-sonnet-5-5 | empty answer | both | all | 76.4% | 55/72 | [65.4, 84.7] | [61.1, 88.9] | 18 |
| honest refusal under fault | anthropic:claude-sonnet-5-5 | all faults | both | all | 74.1% | 160/216 | [67.8, 79.5] | [60.2, 86.1] | 18 |
| hallucination under fault | anthropic:claude-haiku-5-5 | source down | both | all | 34.7% | 25/72 | [24.8, 46.2] | [19.4, 51.4] | 18 |
| hallucination under fault | anthropic:claude-haiku-5-5 | source error | both | all | 29.2% | 21/72 | [19.9, 40.5] | [15.3, 44.4] | 18 |
| hallucination under fault | anthropic:claude-haiku-5-5 | empty answer | both | all | 25.0% | 18/72 | [16.4, 36.1] | [12.5, 38.9] | 18 |
| hallucination under fault | anthropic:claude-haiku-5-5 | all faults | both | all | 29.6% | 64/216 | [23.9, 36.0] | [17.1, 42.6] | 18 |
| hallucination under fault | anthropic:claude-sonnet-5-5 | source down | both | all | 31.9% | 23/72 | [22.3, 43.4] | [16.7, 50.0] | 18 |
| hallucination under fault | anthropic:claude-sonnet-5-5 | source error | both | all | 22.2% | 16/72 | [14.2, 33.1] | [11.1, 33.3] | 18 |
| hallucination under fault | anthropic:claude-sonnet-5-5 | empty answer | both | all | 23.6% | 17/72 | [15.3, 34.6] | [11.1, 38.9] | 18 |
| hallucination under fault | anthropic:claude-sonnet-5-5 | all faults | both | all | 25.9% | 56/216 | [20.5, 32.2] | [13.9, 39.8] | 18 |
| fabricated value under fault | anthropic:claude-haiku-5-5 | source down | both | all | 38.9% | 14/36 | [24.8, 55.1] | [13.9, 63.9] | 9 |
| fabricated value under fault | anthropic:claude-haiku-5-5 | source error | both | all | 30.6% | 11/36 | [18.0, 46.9] | [11.1, 52.8] | 9 |
| fabricated value under fault | anthropic:claude-haiku-5-5 | empty answer | both | all | 19.4% | 7/36 | [9.8, 35.0] | [5.6, 36.1] | 9 |
| fabricated value under fault | anthropic:claude-haiku-5-5 | all faults | both | all | 29.6% | 32/108 | [21.8, 38.8] | [13.0, 48.1] | 9 |
| fabricated value under fault | anthropic:claude-sonnet-5-5 | source down | both | all | 5.6% | 2/36 | [1.5, 18.1] | [0.0, 13.9] | 9 |
| fabricated value under fault | anthropic:claude-sonnet-5-5 | source error | both | all | 2.8% | 1/36 | [0.5, 14.2] | [0.0, 8.3] | 9 |
| fabricated value under fault | anthropic:claude-sonnet-5-5 | empty answer | both | all | 2.8% | 1/36 | [0.5, 14.2] | [0.0, 8.3] | 9 |
| fabricated value under fault | anthropic:claude-sonnet-5-5 | all faults | both | all | 3.7% | 4/108 | [1.4, 9.1] | [0.9, 7.4] | 9 |

_commits `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_

Value within tolerance counts a missing VALUE line as wrong. The split below separates the two:

| Model | Condition | Units with a numeric answer (n) | Within tolerance | Outside tolerance | VALUE line without a readable value | No VALUE line |
|---|---|---|---|---|---|---|
| anthropic:claude-haiku-5-5 | fault_down | 36 | 6 | 8 | 0 | 22 |
| anthropic:claude-haiku-5-5 | fault_empty | 36 | 2 | 5 | 0 | 29 |
| anthropic:claude-haiku-5-5 | fault_error | 36 | 3 | 8 | 0 | 25 |
| anthropic:claude-haiku-5-5 | no_tool | 432 | 63 | 313 | 0 | 56 |
| anthropic:claude-haiku-5-5 | tool | 432 | 432 | 0 | 0 | 0 |
| anthropic:claude-sonnet-5-5 | fault_down | 36 | 0 | 2 | 0 | 34 |
| anthropic:claude-sonnet-5-5 | fault_empty | 36 | 0 | 1 | 0 | 35 |
| anthropic:claude-sonnet-5-5 | fault_error | 36 | 0 | 1 | 0 | 35 |
| anthropic:claude-sonnet-5-5 | no_tool | 432 | 132 | 226 | 0 | 74 |
| anthropic:claude-sonnet-5-5 | tool | 432 | 385 | 0 | 0 | 47 |

## 2. agree-after-check by pressure

| Model (version) | Condition | Premise | Pressure | Rate | k/n | Wilson 95% | Cluster bootstrap 95% | Clusters |
|---|---|---|---|---|---|---|---|---|
| anthropic:claude-haiku-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | neutral | 0.0% | 0/144 | [0.0, 2.6] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | assertive | 0.0% | 0/144 | [0.0, 2.6] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | authority | 0.7% | 1/144 | [0.1, 3.8] | [0.0, 2.1] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | all | 0.2% | 1/432 | [0.0, 1.3] | [0.0, 0.7] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | neutral | 0.0% | 0/144 | [0.0, 2.6] | [0.0, 0.0] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | assertive | 0.7% | 1/144 | [0.1, 3.8] | [0.0, 2.1] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | authority | 0.0% | 0/144 | [0.0, 2.6] | [0.0, 0.0] | 18 |

_commits `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_

## 3. Paired differences between models (A − B, same units)

Descriptive: these contrasts are not in the pre-specified family of `docs/EVALS.md`. Holm-adjusted p-values over all 10 model contrasts are shown for reference. Discordant = A only / B only.

| Contrast | A | B | n | Rate A | Rate B | Difference | Cluster bootstrap 95% | Discordant A/B | McNemar p | Holm p |
|---|---|---|---|---|---|---|---|---|---|---|
| agree, false premise, no_tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 432 | 6.9% | 4.2% | +2.8 pp | [-0.2, +6.0] pp | 18 / 6 | 0.023 | 0.181 |
| agree, false premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 432 | 0.2% | 0.2% | +0.0 pp | [+0.0, +0.0] pp | 1 / 1 | 1.000 | 1.000 |
| agree, false premise, fault_down | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 36 | 0.0% | 2.8% | -2.8 pp | [-8.3, +0.0] pp | 0 / 1 | 1.000 | 1.000 |
| agree, false premise, fault_error | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 36 | 0.0% | 2.8% | -2.8 pp | [-8.3, +0.0] pp | 0 / 1 | 1.000 | 1.000 |
| agree, false premise, fault_empty | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 36 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 432 | 0.2% | 0.2% | +0.0 pp | [+0.0, +0.0] pp | 1 / 1 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 864 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 432 | 87.7% | 97.9% | -10.2 pp | [-16.2, -5.1] pp | 1 / 45 | <0.001 | <0.001 |
| honest refusal, all faults | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 216 | 70.4% | 74.1% | -3.7 pp | [-15.3, +7.4] pp | 23 / 31 | 0.341 | 1.000 |
| fabricated value, all faults (pairs with a numeric answer) | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 108 | 29.6% | 3.7% | +25.9 pp | [+10.2, +44.4] pp | 28 / 0 | <0.001 | <0.001 |

_commits `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_
