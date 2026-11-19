import pytest

from cielo_bench.agent import run_conversation
from cielo_bench.golden import GoldenSet
from cielo_bench.prompts import system_prompt
from cielo_bench.providers.simulated import PERSONAS, SimulatedProvider
from cielo_bench.scoring import parse_verdict, score_trial


def converse(sim, domain, executor, pair, premise, tools, trial_id, pressure="assertive"):
    return run_conversation(
        sim,
        trial_id=trial_id,
        system=system_prompt(domain, pair["lang"]),
        user_text=GoldenSet.question(pair, premise, pressure, pair["lang"]),
        tools=domain.tool_specs() if tools else None,
        executor=executor if tools else None,
    )


def test_deterministic_given_seed(domain, golden, executor):
    a, b = (SimulatedProvider("agreeable", domain, golden, seed=1) for _ in range(2))
    c = SimulatedProvider("agreeable", domain, golden, seed=2)
    texts = {"a": [], "b": [], "c": []}
    for pair in golden.pairs[:40]:
        for name, sim in (("a", a), ("b", b), ("c", c)):
            texts[name].append(
                converse(sim, domain, executor, pair, "false", True, f"t|{pair['pair_id']}")["final_text"]
            )
    assert texts["a"] == texts["b"]
    assert texts["a"] != texts["c"]


def test_indexes_every_pressure_and_language(domain, golden):
    sim = SimulatedProvider("careful", domain, golden)
    assert len(sim._index) == len(golden.pairs) * 2 * 3 * 2


def test_tool_round_trip_and_verdict_lines(domain, golden, executor):
    sim = SimulatedProvider("careful", domain, golden)
    pair = golden.pairs[2]
    out = converse(sim, domain, executor, pair, "false", True, "trial-x", pressure="authority")
    assert len(out["rounds"]) in (1, 2)
    if len(out["rounds"]) == 2:
        assert out["rounds"][0]["tool_results"][0]["result"]["status"] == "ok"
    assert parse_verdict(out["final_text"]) in ("TRUE", "FALSE", "UNKNOWN", None)


def agree_rate(sim, domain, golden, executor, pressure):
    agree = 0
    for pair in golden.pairs:
        out = converse(sim, domain, executor, pair, "false", True, f"{pressure}|{pair['pair_id']}", pressure)
        record = {
            "trial_id": "x",
            "model_label": sim.label,
            "pair_id": pair["pair_id"],
            "lang": pair["lang"],
            "premise": "false",
            "pressure": pressure,
            "condition": "tool",
            "rep": 0,
            "tools_offered": ["body_position"],
            **out,
        }
        agree += score_trial(record, pair, domain)["stance"] == "agree"
    return agree / len(golden.pairs)


def test_personas_and_pressure_move_agreement_in_the_expected_direction(domain, golden, executor):
    careful = SimulatedProvider("careful", domain, golden)
    agreeable = SimulatedProvider("agreeable", domain, golden)
    assert agree_rate(agreeable, domain, golden, executor, "assertive") > agree_rate(
        careful, domain, golden, executor, "assertive"
    )
    assert agree_rate(agreeable, domain, golden, executor, "authority") > agree_rate(
        agreeable, domain, golden, executor, "neutral"
    )


def test_unknown_persona_and_unknown_question(domain, golden):
    with pytest.raises(ValueError):
        SimulatedProvider("reckless", domain, golden)
    sim = SimulatedProvider("careful", domain, golden)
    with pytest.raises(ValueError):
        sim.complete(sim.new_conversation("sys", "What's the weather?", None, "t"))
    assert PERSONAS["careful"].agree_factor("neutral") < PERSONAS["careful"].agree_factor("authority")


def test_guesses_never_land_inside_the_tolerance(domain, golden):
    from cielo_bench.providers.base import Conversation
    from cielo_bench.scoring import format_value, parse_value, value_error, within_tolerance

    sim = SimulatedProvider("agreeable", domain, golden)
    relative = {"kind": "number", "target": 1_234_567.89, "tolerance": 0.005, "tolerance_mode": "rel"}
    zero = {"kind": "number", "target": 0.0, "tolerance": 0.005, "tolerance_mode": "rel"}
    answers = [p["answer"] for p in golden.pairs if p["answer"]] + [relative, zero]
    for i, answer in enumerate(answers):
        for salt in range(25):
            conv = Conversation(system="s", user_text="q", tools=None, trial_id=f"guess-{i}-{salt}")
            guess = sim._guess(conv, {"answer": answer})
            assert not within_tolerance(answer, value_error(answer["kind"], guess, answer["target"]))
            # and the guess survives the round trip through the VALUE line
            parsed = parse_value(f"VALUE: {format_value(answer['kind'], guess)}", answer["kind"], "en")
            assert not within_tolerance(answer, value_error(answer["kind"], parsed, answer["target"]))
