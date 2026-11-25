# ADR-0010 — A distance ladder, a framing control and a two-turn condition

- Status: Accepted · 2026-11-24 (the plan is in `docs/RESEARCH_PLAN.md`; it is not preregistered yet)
- Builds on: ADR-0005 (domain-independent harness), ADR-0009 (near premises). No new tool and no new source.

## Context

ADR-0009 and its pilot (`docs/results/2026-11-near-premises-pilot.md`) closed one lever: with a decisive tool value,
distance between the claim and the truth does not make agreeing after a check likely (0 of 264 for Haiku). A
reanalysis without spend (`scripts/distance_curve.py`) found that a grey zone does exist, between about 2 and 5 units
for Haiku, thinly for Sonnet (4 items) and not at all measured for Opus and Fable, and that between 5 and 10 degrees
and between 3 and 25 minutes there is no data for any model. An external design review also showed that a
neutral-question frame is not a claim (so no contrast against it isolates pressure) and that insistence alone, with
decisive evidence, risks a third floor.

## Decision

1. **A third golden set, `astronomy-ladder-v1`, derived from `astronomy-near-v2`**: one pair per (item, distance step),
   544 pairs, 72 items. Fixtures, tools and scorer are those of the near set; it needs no request to JPL.
2. **A control framing, `referred`**, with the same wording tail as `assertive` and `authority`. The neutral frame
   leaves the confirmatory design.
3. **A condition `tool_insist`**: after the first answer, the conversation forks into two branches (D insistence, N
   neutral challenge) that start from the same answer, so the contrast is paired. The texts are fixed, do not depend on
   the answer and do not ask for a change. They live in the golden set.
4. **Golden sets define their own framings** (`frames`); structure validation, the runner and the CLI default follow it.
   Sets that predate it are unchanged (same hashes).
5. **`VARIANTS` next to `REGISTRY`.** The ladder and the near set reuse the tools of a registered domain. The CLI,
   the docs and the CI see them; the MCP server serves only `REGISTRY`, so its tool names do not change.
6. **The analysis is a module with a pre-specified plan** (`ladder.py`): items as the unit, sign-flip permutation,
   bootstrap within template, exact McNemar for H3, Holm per model. Grey steps are frozen in a config *before* the
   confirmatory run; without it the output is labelled exploratory.
7. **The instrument is validated on planted worlds**, not on the models: a persona with a planted curve and effects,
   and a null persona; the analysis must recover the first and find nothing in the second.

## Consequences

- A first real two-turn run against the API worked (Haiku, 6 trials, US$0.0113 in total, so US$0.0019 per trial: 2.3 times
  a single-turn tool trial at US$0.00081): both branches ran from the same first answer, without a new check. A report for a run with no standard condition used to crash and now says where to look.
- With 72 items and one repetition, the minimum detectable framing effect is about 13.5 pp (see the plan); the null
  persona cannot show equivalence within ±10 pp at that size. Repetitions are part of the confirmatory design.
- The ladder has 9 templates: generalising to "kinds of question" is weak even if the within-item effect is clean.
- The ladder is not part of the standard validation or the power table of the README (it has its own design); its
  golden set is listed there.

## Alternatives rejected

- **Insistence alone.** Closest prior work reports small drops under repeated replies after tool use; it risks a third floor.
- **One pair per item with premises keyed by level.** A schema change that touches the runner, the scorer and every
  report; one pair per step reuses all of them.
- **Using the old neutral frame as the baseline.** It is a question, not a claim.
- **A second provider before the ladder.** It would repeat the floor on another model.
