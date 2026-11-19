"""The shared tool-result contract (cielo_bench.domain), checked on every registered domain."""

import pytest

from cielo_bench.domain import CITATION_FIELDS, FAULT_KINDS, contract_problems
from cielo_bench.domains import AVAILABLE, get_domain
from cielo_bench.golden import load_golden

CITED = {"service": "S", "query": "Q", "retrieved_at_utc": "2026-11-19T00:00:00Z"}


@pytest.mark.parametrize(
    "result,ok",
    [
        ({"status": "ok", "value": 1, "sources": [CITED]}, True),
        ({"status": "ok", "value": 1}, False),
        ({"status": "ok", "sources": []}, False),
        ({"status": "ok", "sources": [{"service": "S", "query": "Q"}]}, False),
        ({"status": "ok", "sources": ["not a dict"]}, False),
        ({"status": "source_unavailable", "source": "S", "reason": "r", "message": "m"}, True),
        ({"status": "source_unavailable", "message": "m", "altitude_deg": 12.0}, False),
        ({"status": "invalid_input", "message": "m"}, True),
        ({"status": "maybe"}, False),
        ("not a dict", False),
    ],
)
def test_contract_problems(result, ok):
    assert (contract_problems(result) == []) is ok


def test_citation_fields_match_the_documented_contract():
    assert CITATION_FIELDS == ("service", "query", "retrieved_at_utc")


@pytest.mark.parametrize("name", AVAILABLE)
def test_every_registered_domain_cites_every_ok_result(name):
    domain = get_domain(name)
    golden = load_golden(domain.golden_path)
    executor = domain.make_executor(offline=True, max_live_requests=0)
    checked = 0
    for pair in golden.pairs:
        for call in pair["expected_calls"]:
            result = executor.execute(call["tool"], call["args"])
            assert result["status"] == "ok", (name, pair["pair_id"], result)
            assert contract_problems(result) == [], (name, pair["pair_id"], contract_problems(result))
            checked += 1
    assert checked >= len(golden.pairs)


@pytest.mark.parametrize("name", AVAILABLE)
@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_every_registered_domain_fails_without_values(name, kind):
    domain = get_domain(name)
    golden = load_golden(domain.golden_path)
    faulty = domain.make_executor(fault_profile=kind)
    for pair in golden.pairs[:: max(1, len(golden.pairs) // 12)]:
        for call in pair["expected_calls"]:
            result = faulty.execute(call["tool"], call["args"])
            assert result["status"] == "source_unavailable", (name, kind, result)
            assert contract_problems(result) == []


def test_external_source_flags():
    assert get_domain("astronomy").external_source is True
    if "tabular" in AVAILABLE:
        assert get_domain("tabular").external_source is False
