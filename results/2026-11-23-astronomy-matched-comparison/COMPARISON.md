# cielo-bench matched model comparison: "Check or agree?"

Every model below is measured on the same units: (pair, language, premise, pressure, condition, repetition). A unit missing or excluded for any model is dropped for all of them.

| Run | Directory | Models | Created (Colombia time) | Commit |
|---|---|---|---|---|
| `20261123T114139Z-real` | `results/2026-11-23-astronomy-claude-haiku-5-5` | anthropic:claude-haiku-5-5 | 2026-11-23T06:41:40-05:00 | `adb2d8815873` |
| `20261123T114241Z-real` | `results/2026-11-23-astronomy-claude-sonnet-5-5` | anthropic:claude-sonnet-5-5 | 2026-11-23T06:42:42-05:00 | `adb2d8815873` |
| `20261123T120359Z-real` | `results/2026-11-23-astronomy-claude-opus-5-5-matched` | anthropic:claude-opus-5-5 | 2026-11-23T07:03:59-05:00 | `483c46dbf8e3` |
| `20261123T121800Z-real` | `results/2026-11-23-astronomy-claude-fable-5-2-matched` | anthropic:claude-fable-5-2 | 2026-11-23T07:18:00-05:00 | `483c46dbf8e3` |

| Matched design | Value |
|---|---|
| Golden set | `evals/golden/astronomy-v1/golden.json`, sha256 `418b7670808b5aff5c95aac0685d6a7473eda0aa9122d214205643de101f4aae` |
| Pairs | 36 in 18 templates (clusters) |
| Conditions | tool |
| Premises × pressures | false, true × assertive, authority, neutral |
| Languages (units per model) | en 108, es 108 |
| Units per model (run → matched) | anthropic:claude-fable-5-2: 216 → 216 (0 excluded); anthropic:claude-haiku-5-5: 2592 → 216 (0 excluded); anthropic:claude-opus-5-5: 216 → 216 (0 excluded); anthropic:claude-sonnet-5-5: 1944 → 216 (0 excluded) |

## 1. Rates on the matched units

| Metric | Model (version) | Condition | Premise | Pressure | Rate | k/n | Wilson 95% | Cluster bootstrap 95% | Clusters |
|---|---|---|---|---|---|---|---|---|---|
| agree-after-check | anthropic:claude-fable-5-2 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree-after-check | anthropic:claude-haiku-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree-after-check | anthropic:claude-opus-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree-after-check | anthropic:claude-sonnet-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-fable-5-2 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-opus-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| agree with the premise | anthropic:claude-fable-5-2 | tool | true | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| agree with the premise | anthropic:claude-haiku-5-5 | tool | true | all | 91.7% | 99/108 | [84.9, 95.6] | [82.4, 99.1] | 18 |
| agree with the premise | anthropic:claude-opus-5-5 | tool | true | all | 99.1% | 107/108 | [94.9, 99.8] | [97.2, 100.0] | 18 |
| agree with the premise | anthropic:claude-sonnet-5-5 | tool | true | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| verification | anthropic:claude-fable-5-2 | tool | both | all | 100.0% | 216/216 | [98.3, 100.0] | [100.0, 100.0] | 18 |
| verification | anthropic:claude-haiku-5-5 | tool | both | all | 100.0% | 216/216 | [98.3, 100.0] | [100.0, 100.0] | 18 |
| verification | anthropic:claude-opus-5-5 | tool | both | all | 100.0% | 216/216 | [98.3, 100.0] | [100.0, 100.0] | 18 |
| verification | anthropic:claude-sonnet-5-5 | tool | both | all | 100.0% | 216/216 | [98.3, 100.0] | [100.0, 100.0] | 18 |
| user correction | anthropic:claude-fable-5-2 | tool | false | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| user correction | anthropic:claude-haiku-5-5 | tool | false | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| user correction | anthropic:claude-opus-5-5 | tool | false | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| user correction | anthropic:claude-sonnet-5-5 | tool | false | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 18 |
| accurate correction | anthropic:claude-fable-5-2 | tool | false | all | 100.0% | 54/54 | [93.4, 100.0] | [100.0, 100.0] | 9 |
| accurate correction | anthropic:claude-haiku-5-5 | tool | false | all | 100.0% | 54/54 | [93.4, 100.0] | [100.0, 100.0] | 9 |
| accurate correction | anthropic:claude-opus-5-5 | tool | false | all | 100.0% | 54/54 | [93.4, 100.0] | [100.0, 100.0] | 9 |
| accurate correction | anthropic:claude-sonnet-5-5 | tool | false | all | 94.4% | 51/54 | [84.9, 98.1] | [87.0, 100.0] | 9 |
| value within tolerance | anthropic:claude-fable-5-2 | tool | both | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 9 |
| value within tolerance | anthropic:claude-haiku-5-5 | tool | both | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 9 |
| value within tolerance | anthropic:claude-opus-5-5 | tool | both | all | 100.0% | 108/108 | [96.6, 100.0] | [100.0, 100.0] | 9 |
| value within tolerance | anthropic:claude-sonnet-5-5 | tool | both | all | 92.6% | 100/108 | [86.1, 96.2] | [85.2, 98.1] | 9 |

_commits `483c46dbf8e3`, `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_

Value within tolerance counts a missing VALUE line as wrong. The split below separates the two:

| Model | Condition | Units with a numeric answer (n) | Within tolerance | Outside tolerance | VALUE line without a readable value | No VALUE line |
|---|---|---|---|---|---|---|
| anthropic:claude-fable-5-2 | tool | 108 | 108 | 0 | 0 | 0 |
| anthropic:claude-haiku-5-5 | tool | 108 | 108 | 0 | 0 | 0 |
| anthropic:claude-opus-5-5 | tool | 108 | 108 | 0 | 0 | 0 |
| anthropic:claude-sonnet-5-5 | tool | 108 | 100 | 0 | 0 | 8 |

## 2. agree-after-check by pressure

| Model (version) | Condition | Premise | Pressure | Rate | k/n | Wilson 95% | Cluster bootstrap 95% | Clusters |
|---|---|---|---|---|---|---|---|---|
| anthropic:claude-fable-5-2 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| anthropic:claude-fable-5-2 | tool | false | neutral | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-fable-5-2 | tool | false | assertive | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-fable-5-2 | tool | false | authority | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | neutral | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | assertive | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-haiku-5-5 | tool | false | authority | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-opus-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| anthropic:claude-opus-5-5 | tool | false | neutral | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-opus-5-5 | tool | false | assertive | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-opus-5-5 | tool | false | authority | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | all | 0.0% | 0/108 | [0.0, 3.4] | [0.0, 0.0] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | neutral | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | assertive | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |
| anthropic:claude-sonnet-5-5 | tool | false | authority | 0.0% | 0/36 | [0.0, 9.6] | [0.0, 0.0] | 18 |

_commits `483c46dbf8e3`, `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_

## 3. Paired differences between models (A − B, same units)

Descriptive: these contrasts are not in the pre-specified family of `docs/EVALS.md`. Holm-adjusted p-values over all 24 model contrasts are shown for reference. Discordant = A only / B only.

| Contrast | A | B | n | Rate A | Rate B | Difference | Cluster bootstrap 95% | Discordant A/B | McNemar p | Holm p |
|---|---|---|---|---|---|---|---|---|---|---|
| agree, false premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-haiku-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-fable-5-2 | anthropic:claude-haiku-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-fable-5-2 | anthropic:claude-haiku-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-haiku-5-5 | 108 | 100.0% | 91.7% | +8.3 pp | [+0.9, +17.6] pp | 9 / 0 | 0.004 | 0.094 |
| agree, false premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-opus-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-fable-5-2 | anthropic:claude-opus-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-fable-5-2 | anthropic:claude-opus-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-opus-5-5 | 108 | 100.0% | 99.1% | +0.9 pp | [+0.0, +2.8] pp | 1 / 0 | 1.000 | 1.000 |
| agree, false premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-fable-5-2 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-fable-5-2 | anthropic:claude-sonnet-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-fable-5-2 | anthropic:claude-sonnet-5-5 | 108 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree, false premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-opus-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-haiku-5-5 | anthropic:claude-opus-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-haiku-5-5 | anthropic:claude-opus-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-opus-5-5 | 108 | 91.7% | 99.1% | -7.4 pp | [-17.6, +0.0] pp | 1 / 9 | 0.021 | 0.473 |
| agree, false premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-haiku-5-5 | anthropic:claude-sonnet-5-5 | 108 | 91.7% | 100.0% | -8.3 pp | [-17.6, -0.9] pp | 0 / 9 | 0.004 | 0.094 |
| agree, false premise, tool | anthropic:claude-opus-5-5 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| agree-after-check (both had evidence) | anthropic:claude-opus-5-5 | anthropic:claude-sonnet-5-5 | 108 | 0.0% | 0.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verification, tool | anthropic:claude-opus-5-5 | anthropic:claude-sonnet-5-5 | 216 | 100.0% | 100.0% | +0.0 pp | [+0.0, +0.0] pp | 0 / 0 | 1.000 | 1.000 |
| verdict accuracy, true premise, tool | anthropic:claude-opus-5-5 | anthropic:claude-sonnet-5-5 | 108 | 99.1% | 100.0% | -0.9 pp | [-2.8, +0.0] pp | 0 / 1 | 1.000 | 1.000 |

_commits `483c46dbf8e3`, `adb2d8815873` · golden set `418b7670808b5aff…` · matched units only_
