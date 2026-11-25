"""The distance ladder: golden set, two-turn agent loop, runner, scorer and the analysis.

The analysis is validated the way the instrument is: on simulated worlds with planted effects (it must
recover them) and with none (it must not invent them).
"""

import json
import re
from collections import Counter, defaultdict

import pytest

from cielo_bench import ladder
from cielo_bench.agent import run_conversation
from cielo_bench.cli import main
from cielo_bench.domains import AVAILABLE, REGISTRY, get_domain
from cielo_bench.domains.astronomy.ladder import FOLLOWUP_FRAMES, FRAMES, LADDER
from cielo_bench.golden import golden_hash, load_golden, validate_structure
from cielo_bench.prompts import system_prompt
from cielo_bench.providers.simulated import PERSONAS, SimulatedProvider
from cielo_bench.report import score_run
from cielo_bench.runner import RunSpec, TrialPlan, followup_messages, plan_trials
from cielo_bench.scoring import score_trial


@pytest.fixture(scope="module")
def ldomain():
    return get_domain("astronomy_ladder")


@pytest.fixture(scope="module")
def lgolden(ldomain):
    return load_golden(ldomain.golden_path)


# ----------------------------------------------------------------------------- the golden set
def test_the_ladder_is_a_variant_the_server_does_not_serve():
    assert "astronomy_ladder" in AVAILABLE and "astronomy_ladder" not in REGISTRY


def test_shape(lgolden):
    assert len(lgolden.pairs) == 544 and len(lgolden.templates) == 9
    items = {p["ladder"]["base_pair"] for p in lgolden.pairs}
    assert len(items) == 72
    steps = defaultdict(list)
    for p in lgolden.pairs:
        steps[p["ladder"]["base_pair"]].append((p["ladder"]["step"], p["ladder"]["nominal"], p["answer"]["kind"]))
    for group in steps.values():
        kind = group[0][2]
        assert [nominal for _, nominal, _ in sorted(group)] == list(LADDER[kind])
    assert validate_structure(lgolden.doc) == []
    assert set(lgolden.doc["frames"]) == {"referred", "assertive", "authority"}


def test_verifies_offline_and_rebuilds_identically(ldomain, lgolden):
    assert ldomain.verify_golden(lgolden) == []
    assert golden_hash(ldomain.build_golden()) == lgolden.sha256


def test_distances_are_exact_and_near_their_nominal_level(lgolden):
    for p in lgolden.pairs:
        meta = p["ladder"]
        assert abs(meta["distance"] - meta["nominal"]) <= 0.5, p["pair_id"]
        assert meta["unit"] in {"deg", "pp", "min"}


def test_one_side_per_item_and_balanced_across_items(lgolden):
    sides = defaultdict(set)
    for p in lgolden.pairs:
        if p["ladder"]["step"] > 0:
            sides[p["ladder"]["base_pair"]].add(p["ladder"]["side"])
    assert all(len(s) == 1 for s in sides.values())  # the side is never confounded with the step
    counts = Counter(next(iter(s)) for s in sides.values())
    assert min(counts.values()) >= 0.35 * sum(counts.values()), counts


def test_the_true_premise_is_the_step_zero_claim(lgolden):
    by_item = defaultdict(dict)
    for p in lgolden.pairs:
        by_item[p["ladder"]["base_pair"]][p["ladder"]["step"]] = p
    for group in by_item.values():
        zero = group[0]["premises"]["false"]["value"]
        assert all(p["premises"]["true"]["value"] == zero for p in group.values())


def test_framings_differ_only_in_the_frame_not_in_the_claim_or_the_tail(lgolden):
    pair = lgolden.pairs[10]
    for lang, tail in (("en", "Right?"), ("es", "¿Cierto?")):
        claim = pair["premises"]["false"]["claim"][lang]
        for framing in FRAMES:
            question = pair["premises"]["false"]["questions"][framing][lang]
            assert claim in question and question.endswith(tail)


def test_followups_carry_the_claim_only_in_the_directional_branch_and_never_ask_for_a_change():
    for lang in ("en", "es"):
        assert "{claim}" in FOLLOWUP_FRAMES["D"][lang] and "{claim}" not in FOLLOWUP_FRAMES["N"][lang]
        for branch in FOLLOWUP_FRAMES:
            assert not re.search(r"change|cambia|reconsider|reconsidera", FOLLOWUP_FRAMES[branch][lang], re.I)


def test_format_examples_cannot_anchor_an_answer(ldomain, lgolden):
    shown = set(ldomain.value_examples("en"))
    shown_numbers = {s.rstrip("°%") for s in shown}
    for p in lgolden.pairs:
        for premise in ("true", "false"):
            display = p["premises"][premise]["display"]
            assert display not in shown and display.rstrip("°%") not in shown_numbers


def test_earlier_golden_sets_are_untouched():
    assert load_golden(get_domain("astronomy").golden_path).sha256 == (
        "418b7670808b5aff5c95aac0685d6a7473eda0aa9122d214205643de101f4aae"
    )


# ----------------------------------------------------------------------------- the two-turn loop
def _conversation(ldomain, lgolden, *, followups, seed=3, persona="ladder-framing", step=3):
    pair = next(p for p in lgolden.pairs if p["ladder"]["step"] == step)
    provider = SimulatedProvider(persona, ldomain, lgolden, seed=seed)
    out = run_conversation(
        provider,
        trial_id="t",
        system=system_prompt(ldomain, pair["lang"]),
        user_text=pair["premises"]["false"]["questions"]["assertive"][pair["lang"]],
        tools=ldomain.tool_specs(),
        executor=ldomain.make_executor(offline=True, max_live_requests=0),
        followups=followups,
    )
    return pair, out


def test_a_trial_without_followups_has_no_followup_field(ldomain, lgolden):
    _, out = _conversation(ldomain, lgolden, followups=None)
    assert "followups" not in out and out["final_text"]


def test_branches_start_from_the_same_first_answer_and_get_their_own_message(ldomain, lgolden):
    _, out = _conversation(ldomain, lgolden, followups={"D": "insist", "N": "challenge"})
    assert set(out["followups"]) == {"D", "N"}
    assert out["followups"]["D"]["user_text"] == "insist" and out["followups"]["N"]["user_text"] == "challenge"
    for branch in out["followups"].values():
        assert branch["rounds"] and branch["final_text"] and branch["error"] is None
    assert out["final_text"] == out["rounds"][-1]["text"]  # the first answer is not overwritten by a branch


def test_cost_counts_every_branch(ldomain, lgolden):
    _, single = _conversation(ldomain, lgolden, followups=None)
    _, branched = _conversation(ldomain, lgolden, followups={"D": "a", "N": "b"})
    assert branched["usage_total"]["output_tokens"] > single["usage_total"]["output_tokens"]


# ----------------------------------------------------------------------------- the runner
def _spec(ldomain, lgolden, **kw):
    return RunSpec(
        domain=ldomain,
        golden=lgolden,
        providers=[SimulatedProvider("ladder-null", ldomain, lgolden)],
        out_dir=None,
        run_id="x",
        simulated=True,
        premises=("false",),
        **kw,
    )


def test_followup_messages_are_built_from_the_golden_set_in_the_trials_language(ldomain, lgolden):
    spec = _spec(ldomain, lgolden, conditions=("tool_insist",), pressures=("assertive",), limit_pairs=4)
    plan = plan_trials(spec)[0]
    pair = lgolden.pair(plan.pair_id)
    texts = followup_messages(lgolden, pair, plan)
    assert pair["premises"]["false"]["claim"][plan.lang] in texts["D"]
    assert texts["N"] == FOLLOWUP_FRAMES["N"][plan.lang]


def test_tool_insist_needs_followup_frames(golden):
    pair = golden.pairs[0]
    plan = TrialPlan("t", 0, pair["pair_id"], "false", "assertive", "tool_insist", pair["lang"], 0)
    with pytest.raises(ValueError, match="followup_frames"):
        followup_messages(golden, pair, plan)


def test_pair_filter_selects_steps_and_rejects_an_empty_match(ldomain, lgolden):
    spec = _spec(ldomain, lgolden, conditions=("tool",), pressures=("assertive",), pair_filter=r"s03$")
    assert {p.pair_id[-3:] for p in plan_trials(spec)} == {"s03"}
    with pytest.raises(ValueError, match="matches no pair"):
        plan_trials(_spec(ldomain, lgolden, pressures=("assertive",), pair_filter="nothing-like-this"))


def test_framings_are_checked_against_the_golden_sets_own_frames(ldomain, lgolden, golden, domain):
    with pytest.raises(ValueError, match="neutral"):
        plan_trials(_spec(ldomain, lgolden, pressures=("neutral",)))
    v1 = RunSpec(domain=domain, golden=golden, providers=[], out_dir=None, run_id="x", simulated=True)
    with pytest.raises(ValueError, match="referred"):
        plan_trials(RunSpec(**{**v1.__dict__, "pressures": ("referred",)}))


def test_default_framings_are_the_golden_sets_own(tmp_path, capsys):
    assert main(["--domain", "astronomy_ladder", "estimate", "--models", "anthropic:claude-haiku-5-5"]) == 0
    assert "1" in capsys.readouterr().out  # the estimate runs with the ladder's own framings


# ----------------------------------------------------------------------------- the scorer
def test_followup_fields_and_ladder_metadata(ldomain, lgolden):
    pair, out = _conversation(ldomain, lgolden, followups={"D": "insist", "N": "challenge"}, step=3)
    record = {
        "trial_id": "t",
        "model_label": "sim:ladder-framing",
        "pair_id": pair["pair_id"],
        "lang": pair["lang"],
        "premise": "false",
        "pressure": "assertive",
        "condition": "tool_insist",
        "tools_offered": ["body_position"],
        **out,
    }
    score = score_trial(record, pair, ldomain)
    assert score["base_pair"] == pair["ladder"]["base_pair"] and score["ladder_step"] == 3
    assert score["ladder_distance"] == pair["ladder"]["distance"]
    for branch in ("D", "N"):
        assert score[f"t2_{branch}_verdict"] in {"TRUE", "FALSE", "UNKNOWN", None}
        assert score[f"t2_{branch}_error"] is False
        assert isinstance(score[f"t2_{branch}_rechecked"], bool)


# ----------------------------------------------------------------------------- the planted personas
def test_planted_curves_fall_with_distance_and_order_the_framings():
    behaviour = PERSONAS["ladder-framing"].ladder
    for framing in ("referred", "assertive", "authority"):
        rates = [behaviour.p_agree(framing, s / 10) for s in range(11)]
        assert rates == sorted(rates, reverse=True) and rates[0] > 0.95 and rates[-1] < 0.05
    mid = 0.4
    assert (
        behaviour.p_agree("referred", mid) < behaviour.p_agree("assertive", mid) < behaviour.p_agree("authority", mid)
    )
    assert behaviour.p_agree("assertive", mid, "D") > behaviour.p_agree("assertive", mid, "N")
    null = PERSONAS["ladder-null"].ladder
    assert null.p_agree("referred", mid) == null.p_agree("authority", mid) == null.p_agree("assertive", mid, "D")


def test_the_simulated_model_refuses_a_second_turn_outside_a_ladder(golden, domain):
    provider = SimulatedProvider("ladder-framing", domain, golden)
    pair = golden.pairs[0]
    with pytest.raises(ValueError, match="distance-ladder"):
        run_conversation(
            provider,
            trial_id="t",
            system=system_prompt(domain, pair["lang"]),
            user_text=pair["premises"]["false"]["questions"]["assertive"][pair["lang"]],
            tools=domain.tool_specs(),
            executor=domain.make_executor(offline=True, max_live_requests=0),
            followups={"D": "x"},
        )


# ----------------------------------------------------------------------------- the analysis, on built rows
def _row(model="m", item="i1", template="t1", step=2, framing="assertive", agree=True, condition="tool", **extra):
    return {
        "model": model,
        "base_pair": item,
        "template": template,
        "ladder_step": step,
        "ladder_distance": float(step),
        "ladder_unit": "deg",
        "value_kind": "angle_deg",
        "pressure": framing,
        "condition": condition,
        "excluded": False,
        "verdict": "TRUE" if agree else "FALSE",
        **extra,
    }


def test_curve_counts_and_flags_a_grey_zone():
    rows = [_row(item=f"i{k}", step=s, agree=(k < n)) for s, n in ((0, 10), (1, 6), (2, 4), (3, 0)) for k in range(10)]
    cells = {c["step"]: c for c in ladder.curve(rows)}
    assert [cells[s]["k"] for s in (0, 1, 2, 3)] == [10, 6, 4, 0] and cells[1]["n_items"] == 10
    lo, hi = cells[1]["wilson"]
    assert lo < 0.6 < hi
    grey = ladder.grey_zone(list(cells.values()))[0]
    assert grey["intermediate_steps"] == [1, 2] and grey["h1_supported"] and not grey["non_monotone"]


def test_a_cliff_is_not_a_grey_zone_and_a_rise_is_flagged():
    cliff = [_row(item=f"i{k}", step=s, agree=(s == 0)) for s in range(4) for k in range(10)]
    assert not ladder.grey_zone(ladder.curve(cliff))[0]["h1_supported"]
    rising = [_row(item=f"i{k}", step=s, agree=(k < (2 if s == 0 else 8))) for s in range(2) for k in range(10)]
    assert ladder.grey_zone(ladder.curve(rising))[0]["non_monotone"]


def test_excluded_and_other_condition_rows_do_not_count():
    rows = [_row(), _row(excluded=True), _row(condition="no_tool")]
    assert sum(c["n"] for c in ladder.curve(rows)) == 1


def _framing_rows(delta, n_items=30, templates=("a", "b", "c")):
    rows = []
    for k in range(n_items):
        t = templates[k % len(templates)]
        for framing, rate in (("referred", 0.3), ("assertive", 0.3 + delta)):
            agree = (k % 10) < round(rate * 10)
            rows.append(_row(item=f"i{k}", template=t, framing=framing, agree=agree))
    return rows


def test_framing_contrast_has_the_right_sign_size_and_equivalence():
    steps = {"angle_deg": [2]}
    up = ladder.framing_contrast(_framing_rows(0.4), "m", "assertive", "referred", steps, bound=0.10)
    assert up["n_items"] == 30 and up["diff"] == pytest.approx(0.4) and up["p"] < 0.01 and up["equivalent"] is False
    none = ladder.framing_contrast(_framing_rows(0.0), "m", "assertive", "referred", steps, bound=0.10)
    assert none["diff"] == 0.0 and none["p"] == 1.0 and none["equivalent"] is True
    down = ladder.framing_contrast(_framing_rows(-0.2), "m", "assertive", "referred", steps)
    assert down["diff"] == pytest.approx(-0.2)  # the opposite sign is reported, not hidden


def test_the_contrast_uses_only_the_frozen_steps():
    rows = [*_framing_rows(0.4), _row(item="i0", step=5, framing="assertive", agree=True)]
    out = ladder.framing_contrast(rows, "m", "assertive", "referred", {"angle_deg": [2]})
    assert out["diff"] == pytest.approx(0.4)


def _insist_row(item, first, d, n, model="m", step=2, framing="assertive", **extra):
    return _row(
        model=model,
        item=item,
        step=step,
        framing=framing,
        agree=first,
        condition="tool_insist",
        t2_D_verdict="TRUE" if d else "FALSE",
        t2_N_verdict="TRUE" if n else "FALSE",
        t2_D_error=False,
        t2_N_error=False,
        t2_D_rechecked=True,
        t2_N_rechecked=False,
        t2_D_value_toward_claim=True,
        t2_N_value_toward_claim=False,
        **extra,
    )


def test_insistence_counts_switches_from_a_first_answer_that_disagreed():
    rows = [_insist_row(f"i{k}", first=(k < 5), d=True, n=(k % 4 == 0)) for k in range(20)]
    out = ladder.insistence(rows, "m")
    assert out["n_units"] == 20 and out["n_first_not_true"] == 15
    assert out["switch"]["rate_a"] == 1.0 and out["switch"]["rate_b"] == pytest.approx(3 / 15)
    assert out["diff"] > 0.7 and out["p"] < 0.001
    assert out["rechecked_D"] == 1.0 and out["rechecked_N"] == 0.0
    assert out["value_toward_claim_D"] == 1.0 and out["value_toward_claim_N"] == 0.0


def test_insistence_ignores_other_framings_failed_branches_and_other_steps():
    rows = [
        _insist_row("i1", False, True, False),
        _insist_row("i2", False, True, False, framing="authority"),
        {**_insist_row("i3", False, True, False), "t2_D_error": True},
        _insist_row("i4", False, True, False, step=7),
    ]
    assert ladder.insistence(rows, "m", {"angle_deg": [2]})["n_units"] == 1


def test_holm_is_applied_per_model_over_the_contrasts_that_ran():
    steps = {"angle_deg": [2]}
    rows = _framing_rows(0.4)
    rows += [{**r, "pressure": "authority"} for r in rows if r["pressure"] == "assertive"]
    result = ladder.analyze(rows, {"grey_steps": steps})
    contrasts = result["models"]["m"]["contrasts"]
    assert [c["contrast"] for c in contrasts] == ["assertive - referred", "authority - assertive"]
    assert all(c["holm_p"] >= c["p"] for c in contrasts)
    assert not ladder.analyze(rows)["models"] and not ladder.analyze(rows)["confirmatory"]


# ----------------------------------------------------------------------------- the analysis, on planted worlds
@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    out = tmp_path_factory.mktemp("ladder-worlds") / "run"
    code = main(
        [
            "--domain", "astronomy_ladder", "run", "--simulated",
            "--models", "sim:ladder-framing,sim:ladder-null",
            "--premises", "false", "--conditions", "tool,tool_insist",
            "--pair-filter", r"s0[2-4]$", "--out", str(out), "--yes",
        ]
    )  # fmt: skip
    assert code == 0
    _, scored, _ = score_run(out)
    config = {
        "grey_steps": {"angle_deg": [2, 3, 4], "number": [2, 3, 4], "clock_time": [2, 3, 4]},
        "equivalence_bound": 0.10,
    }
    return out, ladder.analyze(scored, config)


def _by(result, model):
    return {c["contrast"]: c for c in result["models"][model]["contrasts"]}


def test_planted_framing_and_insistence_effects_are_recovered(worlds):
    _, result = worlds
    planted = _by(result, "sim:ladder-framing")
    for name in ("assertive - referred", "authority - assertive"):
        assert planted[name]["diff"] > 0.10 and planted[name]["holm_p"] < 0.01
        assert planted[name]["ci"][0] > 0
    assert planted["D - N"]["diff"] > 0.3 and planted["D - N"]["holm_p"] < 0.001


def test_a_world_without_effects_produces_no_effect(worlds):
    _, result = worlds
    null = _by(result, "sim:ladder-null")
    assert all(c["holm_p"] > 0.05 for c in null.values())
    assert abs(null["assertive - referred"]["diff"]) < 0.10 and null["D - N"]["diff"] == 0.0


def test_the_curve_finds_the_planted_grey_zone(worlds):
    _, result = worlds
    grey = [g for g in result["grey_zone"] if g["model"] == "sim:ladder-framing" and g["framing"] == "referred"]
    assert any(g["h1_supported"] for g in grey)


def test_the_cli_writes_the_report_and_labels_an_unfrozen_analysis(worlds, tmp_path):
    run, _ = worlds
    assert main(["ladder", str(run), "--out", str(tmp_path)]) == 0
    text = (tmp_path / "LADDER.md").read_text(encoding="utf-8")
    assert "Exploratory" in text and "confirmatory family" not in text
    summary = json.loads((tmp_path / "ladder_summary.json").read_text(encoding="utf-8"))
    assert summary["confirmatory"] is False
    config = tmp_path / "frozen.json"
    config.write_text(json.dumps({"grey_steps": {"angle_deg": [2]}}), encoding="utf-8")
    assert main(["ladder", str(run), "--config", str(config), "--out", str(tmp_path)]) == 0
    assert "confirmatory family" in (tmp_path / "LADDER.md").read_text(encoding="utf-8")


def test_the_standard_report_builds_for_a_run_with_only_the_two_turn_condition(tmp_path):
    out = tmp_path / "run"
    code = main(
        [
            "--domain", "astronomy_ladder", "run", "--simulated", "--models", "sim:ladder-null",
            "--premises", "false", "--conditions", "tool_insist", "--pressures", "assertive",
            "--limit", "4", "--out", str(out), "--yes",
        ]
    )  # fmt: skip
    assert code == 0
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "No standard condition in this run" in report and "![" not in report
