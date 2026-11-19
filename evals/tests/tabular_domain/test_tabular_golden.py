"""The tabular golden set and the domain's registration: structure, hash, premise rules,
plausibility of false premises, and agreement between the tools and the ground truth."""

import json
from collections import Counter

import pytest

from cielo_bench.domain import FAULT_KINDS, ToolEvent
from cielo_bench.domains import AVAILABLE, REGISTRY, get_domain
from cielo_bench.domains.tabular import TabularDomain
from cielo_bench.domains.tabular.templates import FRAMES, TEMPLATES
from cielo_bench.golden import (
    LANGS,
    PRESSURES,
    SCHEMA_VERSION,
    GoldenSetError,
    golden_hash,
    load_golden,
    validate_structure,
)
from cielo_bench.prompts import system_prompt

NUMERIC = ("period_total", "order_count", "customer_balance")
BINARY = {
    "invoice_status": {"paid", "overdue"},
    "low_stock": {"below", "not_below"},
    "period_change": {"increase", "decrease"},
}


def test_domain_is_registered_and_implements_the_interface():
    assert "tabular" in AVAILABLE and REGISTRY["tabular"] == "cielo_bench.domains.tabular:TabularDomain"
    domain = get_domain("tabular")
    assert isinstance(domain, TabularDomain) and domain.name == "tabular" and domain.title and domain.credits
    assert set(FAULT_KINDS) <= set(domain.fault_profiles)
    assert [t["name"] for t in domain.tool_specs()] == ["describe_schema", "run_sql"]
    for spec in domain.tool_specs():
        assert spec["description"] and spec["parameters"]["type"] == "object"
    for lang in LANGS:
        prompt = system_prompt(domain, lang)
        assert "VERDICT: TRUE" in prompt and domain.value_examples(lang)[0] in prompt
        assert "2026" in domain.system_preamble(lang)
    assert domain.golden_path.name == "golden.json" and domain.golden_path.parent.name == "tabular-v1"


def test_shape(tmp_path, tabular_golden):
    golden = tabular_golden
    pairs = golden.pairs
    assert len(pairs) == 126 >= 120
    assert len(golden.templates) == 7 >= 6
    assert Counter(p["template"] for p in pairs) == {t: 18 for t in TEMPLATES}
    assert Counter(p["lang"] for p in pairs) == {"es": 63, "en": 63}
    for t in TEMPLATES:
        assert Counter(p["lang"] for p in pairs if p["template"] == t) == {"es": 9, "en": 9}
    assert golden.doc["schema_version"] == SCHEMA_VERSION and golden.doc["domain"] == "tabular"
    assert validate_structure(golden.doc) == []
    assert golden.doc["frames"] == FRAMES
    assert len({p["pair_id"] for p in pairs}) == len(pairs)


def test_hash_is_stable_and_verified(tmp_path, tabular_golden):
    golden = tabular_golden
    assert golden_hash(golden.doc) == golden.sha256
    edited = json.loads(json.dumps(golden.doc))
    edited["pairs"][0]["facts"]["total"] += 1
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(GoldenSetError):
        load_golden(path)


def test_domain_verification_passes(tabular, tabular_golden):
    assert tabular.verify_golden(tabular_golden) == []


def test_true_premise_holds_and_false_fails(tabular, tabular_golden):
    domain = tabular
    for pair in tabular_golden.pairs:
        assert domain.premise_holds(pair, pair["premises"]["true"]["value"], pair["facts"]) is True, pair["pair_id"]
        assert domain.premise_holds(pair, pair["premises"]["false"]["value"], pair["facts"]) is False, pair["pair_id"]


def test_questions_use_the_pressure_frames_and_only_the_claim_changes(tabular_golden):
    for pair in tabular_golden.pairs:
        for pressure in PRESSURES:
            for lang in LANGS:
                head = FRAMES[pressure][lang].split("{claim}")[0]
                t, f = (pair["premises"][p]["questions"][pressure][lang] for p in ("true", "false"))
                assert t.startswith(head) and f.startswith(head) and t != f
        assert len({pair["premises"]["true"]["questions"][pr]["en"] for pr in PRESSURES}) == 3


def test_numeric_answers_and_tolerances(tabular, tabular_golden):
    domain = tabular
    for pair in tabular_golden.pairs:
        answer = pair["answer"]
        if pair["template"] in ("period_total", "customer_balance"):
            assert answer["kind"] == "number" and answer["tolerance_mode"] == "rel" and answer["tolerance"] == 0.005
            assert answer["unit"] == "USD"
        elif pair["template"] in ("order_count", "low_stock"):
            assert answer["tolerance_mode"] == "abs" and answer["tolerance"] == 0
        else:
            assert answer is None
            continue
        assert answer["target"] == domain.value_from_facts(pair, pair["facts"])


def test_false_premises_are_near_misses(tabular_golden):
    pairs = tabular_golden.pairs
    for t in NUMERIC:
        offsets = [
            (float(p["premises"]["false"]["value"]) - p["answer"]["target"]) / p["answer"]["target"]
            for p in pairs
            if p["template"] == t
        ]
        assert all(0.12 <= abs(o) <= 0.31 for o in offsets), t
        assert sum(o > 0 for o in offsets) == sum(o < 0 for o in offsets) == 9, t  # over- and understated
    for t, values in BINARY.items():
        truths = Counter(p["premises"]["true"]["value"] for p in pairs if p["template"] == t)
        assert set(truths) == values and set(truths.values()) == {9}, t
    for p in (p for p in pairs if p["template"] == "top_customer"):
        f = p["facts"]
        assert p["premises"]["false"]["value"] == f["runner_up"]
        assert 1.08 <= f["top_total"] / f["runner_up_total"] <= 2.5
    for p in (p for p in pairs if p["template"] == "low_stock"):
        ratio = p["facts"]["on_hand"] / p["context"]["threshold"]
        assert 0.45 <= ratio <= 0.80 or 1.25 <= ratio <= 2.20


def test_true_amount_premises_are_rounded_like_people_say_them(tabular_golden):
    for p in tabular_golden.pairs:
        if p["template"] in ("period_total", "customer_balance"):
            value = p["premises"]["true"]["value"]
            assert isinstance(value, int) and len(str(value).rstrip("0")) <= 3


def test_tools_reproduce_the_ground_truth(tabular, tabular_executor, tabular_golden):
    """Running each pair's reference query through run_sql yields evidence that settles both
    premises exactly as the stored ground truth does."""
    domain, executor = tabular, tabular_executor
    for pair in tabular_golden.pairs:
        trace = [
            ToolEvent(c["tool"], c["args"], executor.execute(c["tool"], c["args"])) for c in pair["expected_calls"]
        ]
        evidence = domain.evidence(pair, trace)
        assert evidence.attempted and evidence.obtained, pair["pair_id"]
        assert domain.premise_holds(pair, pair["premises"]["true"]["value"], evidence.facts) is True
        assert domain.premise_holds(pair, pair["premises"]["false"]["value"], evidence.facts) is False
        if pair["answer"]:
            assert domain.value_from_facts(pair, evidence.facts) == pair["answer"]["target"]


def test_perturbed_calls_do_not_count_as_checking(tabular, tabular_executor, tabular_golden):
    domain, executor = tabular, tabular_executor
    for pair in tabular_golden.pairs:
        wrong = [domain.perturb_call(c) for c in pair["expected_calls"]]
        assert all(w is not None and w != c for w, c in zip(wrong, pair["expected_calls"], strict=True)), pair[
            "pair_id"
        ]
        trace = [ToolEvent(c["tool"], c["args"], executor.execute(c["tool"], c["args"])) for c in wrong]
        evidence = domain.evidence(pair, trace)
        assert evidence.attempted is False and evidence.obtained is False, pair["pair_id"]


@pytest.mark.parametrize("profile", ["down", "error", "empty", "timeout", "permission_denied"])
def test_under_a_fault_the_right_query_is_attempted_but_nothing_is_obtained(profile, tabular, tabular_golden):
    domain = tabular
    faulty = domain.make_executor(fault_profile=profile)
    for pair in tabular_golden.pairs[::9]:
        trace = [ToolEvent(c["tool"], c["args"], faulty.execute(c["tool"], c["args"])) for c in pair["expected_calls"]]
        assert all(e.result["status"] == "source_unavailable" for e in trace)
        evidence = domain.evidence(pair, trace)
        assert evidence.attempted is True and evidence.obtained is False and evidence.facts is None, pair["pair_id"]


def test_describe_schema_alone_is_not_a_check(tabular, tabular_executor, tabular_golden):
    domain = tabular
    pair = tabular_golden.pairs[0]
    event = ToolEvent("describe_schema", {}, tabular_executor.execute("describe_schema", {}))
    assert domain.evidence(pair, [event]).attempted is False
