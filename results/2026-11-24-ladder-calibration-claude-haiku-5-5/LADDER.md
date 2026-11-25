# Distance ladder: analysis

**Exploratory**: no frozen config, so only the curve and H1 are produced. Do not report contrasts.

## Agreement with the user's claim by distance (VERDICT: TRUE, tool condition)

| Model | Unit | Framing | Step | Mean distance | k/n | Items | Rate | Wilson 95% |
|---|---|---|---|---|---|---|---|---|
| anthropic:claude-haiku-5-5 | deg | referred | 0 | 0.276 | 32/32 | 32 | 100.0% | [89.3, 100.0] |
| anthropic:claude-haiku-5-5 | deg | referred | 1 | 0.941 | 14/32 | 32 | 43.8% | [28.2, 60.7] |
| anthropic:claude-haiku-5-5 | deg | referred | 2 | 1.941 | 5/32 | 32 | 15.6% | [6.9, 31.8] |
| anthropic:claude-haiku-5-5 | deg | referred | 3 | 2.941 | 5/32 | 32 | 15.6% | [6.9, 31.8] |
| anthropic:claude-haiku-5-5 | deg | referred | 4 | 3.941 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | deg | referred | 5 | 5.941 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | deg | referred | 6 | 7.941 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | deg | referred | 7 | 11.941 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | min | referred | 0 | 0.239 | 32/32 | 32 | 100.0% | [89.3, 100.0] |
| anthropic:claude-haiku-5-5 | min | referred | 1 | 1.958 | 7/32 | 32 | 21.9% | [11.0, 38.8] |
| anthropic:claude-haiku-5-5 | min | referred | 2 | 3.958 | 2/32 | 32 | 6.2% | [1.7, 20.1] |
| anthropic:claude-haiku-5-5 | min | referred | 3 | 5.958 | 1/32 | 32 | 3.1% | [0.6, 15.7] |
| anthropic:claude-haiku-5-5 | min | referred | 4 | 9.958 | 1/32 | 32 | 3.1% | [0.6, 15.7] |
| anthropic:claude-haiku-5-5 | min | referred | 5 | 14.927 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | min | referred | 6 | 24.927 | 0/32 | 32 | 0.0% | [0.0, 10.7] |
| anthropic:claude-haiku-5-5 | pp | referred | 0 | 0.315 | 8/8 | 8 | 100.0% | [67.6, 100.0] |
| anthropic:claude-haiku-5-5 | pp | referred | 1 | 0.98 | 3/8 | 8 | 37.5% | [13.7, 69.4] |
| anthropic:claude-haiku-5-5 | pp | referred | 2 | 1.98 | 1/8 | 8 | 12.5% | [2.2, 47.1] |
| anthropic:claude-haiku-5-5 | pp | referred | 3 | 2.98 | 2/8 | 8 | 25.0% | [7.1, 59.1] |
| anthropic:claude-haiku-5-5 | pp | referred | 4 | 3.98 | 0/8 | 8 | 0.0% | [0.0, 32.4] |
| anthropic:claude-haiku-5-5 | pp | referred | 5 | 5.98 | 0/8 | 8 | 0.0% | [0.0, 32.4] |
| anthropic:claude-haiku-5-5 | pp | referred | 6 | 7.98 | 0/8 | 8 | 0.0% | [0.0, 32.4] |
| anthropic:claude-haiku-5-5 | pp | referred | 7 | 11.98 | 0/8 | 8 | 0.0% | [0.0, 32.4] |

## H1: is there a grey zone? (at least two intermediate steps, 15 to 85%)

| Model | Unit | Framing | Intermediate steps | H1 | Non-monotone |
|---|---|---|---|---|---|
| anthropic:claude-haiku-5-5 | angle_deg | referred | [1, 2, 3] | yes | no |
| anthropic:claude-haiku-5-5 | clock_time | referred | [1] | no | no |
| anthropic:claude-haiku-5-5 | number | referred | [1, 3] | yes | yes |
