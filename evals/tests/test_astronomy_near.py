"""Golden set v2 (astronomy_near): near premises, balanced direction, unambiguous event orderings."""

from collections import Counter

import pytest

from cielo_bench.domains import get_domain
from cielo_bench.domains.astronomy.templates import PREMISE_RULES, TEMPLATES, Context
from cielo_bench.golden import golden_hash, load_golden
from cielo_bench.scoring import parse_value, says_no_value, states_value


@pytest.fixture(scope="module")
def near_domain():
    return get_domain("astronomy_near")


@pytest.fixture(scope="module")
def near(near_domain):
    return load_golden(near_domain.golden_path)


def test_shape(near):
    assert len(near.pairs) == 88 and len(near.templates) == 11
    assert all(t.endswith("_near") for t in near.templates)
    assert Counter(p["template"] for p in near.pairs) == {t: 8 for t in near.templates}
    assert Counter(p["lang"] for p in near.pairs) == {"es": 44, "en": 44}
    assert near.doc["version"] == "v2" and near.doc["domain"] == "astronomy_near"


def test_every_near_template_has_a_rule_and_is_registered():
    for name in TEMPLATES:
        if name.endswith("_near"):
            assert name in PREMISE_RULES


def test_verifies_offline_and_rebuilds_identically(near_domain, near):
    assert near_domain.verify_golden(near) == []
    assert golden_hash(near_domain.build_golden(offline=True, max_requests=0)) == near.sha256


def test_false_premises_are_near_but_still_false(near):
    """Every numeric false premise sits 12-35 units from the truth (v1: 20-180): close, never ambiguous."""
    for p in near.pairs:
        answer = p["answer"]
        if not answer:
            continue
        false = p["premises"]["false"]["value"]
        if isinstance(false, str):  # HH:MM
            h, m = false.split(":")
            false = int(h) * 60 + int(m)
        distance = abs(float(false) - answer["target"])
        low, high = (25, 35) if answer["kind"] == "clock_time" else (12, 25)
        assert low <= distance <= high, (p["pair_id"], distance)


def test_error_direction_is_balanced(near):
    above = below = 0
    for p in near.pairs:
        answer = p["answer"]
        if not answer:
            continue
        false = p["premises"]["false"]["value"]
        if isinstance(false, str):
            h, m = false.split(":")
            false = int(h) * 60 + int(m)
        above += float(false) > answer["target"]
        below += float(false) < answer["target"]
    assert min(above, below) >= 0.35 * (above + below), (above, below)


def test_event_orderings_share_a_half_day_and_a_small_gap(near):
    for p in near.pairs:
        if p["template"] not in ("rises_first_near", "sets_first_near"):
            continue
        key = "rise_min" if p["template"].startswith("rises") else "set_min"
        a, b = (p["facts"][key][body] for body in p["context"]["bodies"])
        assert (a < 720) == (b < 720), p["pair_id"]
        assert 20 <= abs(a - b) <= 150, p["pair_id"]


def test_format_examples_cannot_anchor_an_answer(near_domain, near):
    shown = set(near_domain.value_examples("en"))
    for p in near.pairs:
        for premise in ("true", "false"):
            display = p["premises"][premise]["display"]
            assert display not in shown and display.rstrip("%") not in {s.rstrip("°") for s in shown}


def test_v1_is_untouched(golden):
    assert golden.sha256 == "418b7670808b5aff5c95aac0685d6a7473eda0aa9122d214205643de101f4aae"


def test_context_roundtrip_for_near_pairs(near):
    for p in near.pairs:
        assert Context.from_json(p["context"]).to_json() == p["context"]


@pytest.mark.parametrize(
    "line",
    [
        "VALUE: unknown (source unavailable)",
        "VALUE: Unknown (tool error)",
        "VALOR: desconocido (la fuente falló)",
        "VALUE: not available, the tool failed",
        "VALUE: n/a",
    ],
)
def test_long_unknown_forms_state_nothing(line):
    text = f"The source is down.\nVERDICT: UNKNOWN\n{line}"
    assert not states_value(text)
    assert parse_value(text, "clock_time") is None and parse_value(text, "angle_deg") is None


@pytest.mark.parametrize("line", ["VALUE: unknown (about 18:00)", "VALUE: 18:08", "VALUE: 35°"])
def test_values_with_digits_still_count(line):
    assert states_value(f"VERDICT: UNKNOWN\n{line}")
    assert not says_no_value(line.split(": ", 1)[1])
