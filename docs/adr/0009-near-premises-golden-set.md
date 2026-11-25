# ADR-0009 — A second astronomy golden set with premises close to the truth

- Status: Accepted · 2026-11-24, with a finding: the pilot (`docs/results/2026-11-near-premises-pilot.md`) shows that near premises do not break the floor with the tool (0 of 264 for Haiku). The set stays, as an unambiguous item bank with balanced error direction (its effect on the no-tool baseline is not established: the comparison with v1 is not like for like), but the lever for a harder test is insistence over several turns
- Builds on: ADR-0005 (domain-independent harness) and ADR-0008 (astronomy tools). No new tool and no new source: it reuses the 102 cached Horizons requests.

## Context

The v1.1 results note (`docs/results/2026-11-first-real-runs.md`, sections 2, 6 and 7) found a difficulty floor:

- With the tool, all four models verified on every astronomy trial; agree-after-check was 2 in 1,080, both on one ambiguous item.
- The false premises are far from the truth (30° for angles, 40 points for the Moon, 1.5 to 3 hours for times), so many can be rejected from general knowledge, and the benchmark cannot rank models.
- `sets_first` and five `rises_first` pairs mix events from different nights.
- The prompt's format examples (`35°`, `19:40`) equal premise values of some items.

## Decision

1. **A second golden set, `astronomy-near-v2`, in a second domain name (`astronomy_near`)**, instead of a switch inside the first. A golden set is identified by its hash and its templates; the v1 set (`418b7670…`) and every v1.1 result stay reproducible byte for byte.
2. **Eleven `_near` templates**: same questions, same tools, same scorer, with the false value about half as far from the truth and the failure threshold tightened to match (rules in `templates.PREMISE_RULES`). Eight pairs each, 88 in total. Binary templates are left out: a binary claim has no distance.
3. **Event orderings** use events in the same half of the local day, 20 to 150 minutes apart.
4. **Balanced direction**: the sign of the error is chosen by a hash of the context, not always upward.
5. **Format examples that cannot be a premise value** (`52°`, `07:23`).
6. **A golden set carries only the premise rules of its own templates**, so a new set never changes an old hash.

## Consequences

- Cost: 88 pairs × 2 conditions × 2 premises × 3 pressures = 1,056 Haiku trials, about US$0.45 to US$2.54 at list prices (`cielo-bench estimate`).
- **A limit that is part of the decision.** With the tool returning the exact value, a premise 15° off is rejected as easily as one 30° off. Closeness may raise the no-tool baseline from knowledge to guessing. Whether it also breaks the floor with the tool is an empirical question, and the pilot is the test. Result: it does not (0 of 264). If it does not, the next lever is not distance but the form of the interaction: multi-turn insistence, free-form answers, and tool outputs that are not decisive (planned for v1.3).
- A "near" premise at 12° or 25 minutes is still not a borderline case. A graded ladder of distances, including values in the grey zone, would need an unambiguous definition of false, and is left open.
- The v2 set has 88 pairs and 11 clusters. Its intervals are as wide as v1's: it supports a difference between conditions, not a ranking of models.

## Alternatives rejected

- **Change v1 in place.** It would break the reproducibility of the published results.
- **A switch (`--difficulty near`) on the existing domain.** It hides the difficulty in run flags and not in the set's identity and hash.
- **A second provider first.** It would repeat the floor on another model.
