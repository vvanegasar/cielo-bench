"""JPL Horizons client: caching, honest User-Agent, serialization and every failure path."""

import json
import threading
import time
from datetime import datetime

import httpx
import pytest
from astro_support import UTC, horizons_body

from cielo_bench.cache import DiskCache
from cielo_bench.config import DEFAULT_USER_AGENT
from cielo_bench.domain import BUDGET_EXHAUSTED
from cielo_bench.domains.astronomy.horizons import HorizonsClient, SourceUnavailable

GOOD = horizons_body(datetime(2026, 12, 12, 5, 0, tzinfo=UTC), 3, lambda i: 10.0 + i)
Q1 = {"format": "json", "COMMAND": "'699'"}
Q2 = {"format": "json", "COMMAND": "'599'"}


class Recorder(httpx.BaseTransport):
    def __init__(self, responder):
        self.responder = responder
        self.requests: list[httpx.Request] = []

    def handle_request(self, request):
        self.requests.append(request)
        return self.responder(request)


def client(tmp_path, transport, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("min_interval_s", 0)
    return HorizonsClient(DiskCache(tmp_path), transport=transport, **kw)


def test_fetch_caches_and_second_call_uses_cache(tmp_path):
    t = Recorder(lambda r: httpx.Response(200, content=GOOD))
    c = client(tmp_path, t)
    first = c.fetch(Q1)
    second = c.fetch(Q1)
    assert first.from_cache is False and second.from_cache is True
    assert first.sha256 == second.sha256
    assert len(t.requests) == 1
    assert c.live_requests == 1


def test_user_agent_is_honest_and_has_no_personal_data(tmp_path):
    t = Recorder(lambda r: httpx.Response(200, content=GOOD))
    client(tmp_path, t).fetch(Q1)
    ua = t.requests[0].headers["user-agent"]
    assert ua == DEFAULT_USER_AGENT
    assert ua.startswith("cielo-bench/") and "non-commercial research benchmark" in ua
    assert "@" not in ua and "gmail" not in ua.lower()


@pytest.mark.parametrize(
    "responder,reason,calls",
    [
        (lambda r: httpx.Response(503, text="down"), "http_503", 3),
        (lambda r: httpx.Response(200, text="<html>oops</html>"), "malformed_response", 3),
        (lambda r: httpx.Response(200, content=json.dumps({"error": "bad query"}).encode()), "upstream_error", 1),
        (lambda r: httpx.Response(200, content=json.dumps({"result": "no table here"}).encode()), "no_ephemeris", 1),
        (lambda r: httpx.Response(404, text="nope"), "http_404", 1),
        (
            lambda r: httpx.Response(200, content=json.dumps({"result": "x\n$$SOE\n$$EOE\n"}).encode()),
            "empty_response",
            1,
        ),
    ],
)
def test_failures_raise_source_unavailable_and_cache_nothing(tmp_path, responder, reason, calls):
    t = Recorder(responder)
    c = client(tmp_path, t, retries=2)
    with pytest.raises(SourceUnavailable) as err:
        c.fetch(Q1)
    assert err.value.reason == reason
    assert len(t.requests) == calls
    assert DiskCache(tmp_path).keys() == []


def test_timeout_is_source_unavailable(tmp_path):
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SourceUnavailable) as err:
        client(tmp_path, Recorder(boom), retries=1).fetch(Q1)
    assert err.value.reason == "timeout"


def test_offline_cache_miss_never_touches_the_network(tmp_path):
    t = Recorder(lambda r: httpx.Response(200, content=GOOD))
    with pytest.raises(SourceUnavailable) as err:
        client(tmp_path, t, offline=True).fetch(Q1)
    assert err.value.reason == "offline_cache_miss"
    assert t.requests == []


def test_request_cap(tmp_path):
    c = client(tmp_path, Recorder(lambda r: httpx.Response(200, content=GOOD)), max_live_requests=1)
    c.fetch(Q1)
    with pytest.raises(SourceUnavailable) as err:
        c.fetch(Q2)
    assert err.value.reason == BUDGET_EXHAUSTED


@pytest.mark.parametrize("profile", ["down", "error", "empty", "malformed", "timeout"])
def test_fault_profile_bypasses_a_warm_cache(tmp_path, profile):
    client(tmp_path, Recorder(lambda r: httpx.Response(200, content=GOOD))).fetch(Q1)  # warm the cache
    faulty = HorizonsClient(DiskCache(tmp_path), fault_profile=profile, sleep=lambda s: None)
    with pytest.raises(SourceUnavailable):
        faulty.fetch(Q1)


def test_cache_integrity_error_is_source_unavailable(tmp_path):
    c = client(tmp_path, Recorder(lambda r: httpx.Response(200, content=GOOD)))
    c.fetch(Q1)
    for path in tmp_path.glob("*.json.gz"):
        path.write_bytes(b"garbage")
    with pytest.raises(SourceUnavailable) as err:
        c.fetch(Q1)
    assert err.value.reason == "cache_integrity_error"


def test_requests_are_serialized(tmp_path):
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(request):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.03)
        with lock:
            state["now"] -= 1
        return httpx.Response(200, content=GOOD)

    c = client(tmp_path, Recorder(slow))
    queries = [{"format": "json", "COMMAND": f"'{i}'"} for i in range(6)]
    threads = [threading.Thread(target=c.fetch, args=(q,)) for q in queries]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert state["max"] == 1
    assert c.live_requests == 6


def test_request_log_records_real_requests_only(tmp_path):
    log = tmp_path / "log.jsonl"
    client(tmp_path / "c", Recorder(lambda r: httpx.Response(200, content=GOOD)), request_log=log).fetch(Q1)
    entries = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(entries) == 1 and entries[0]["outcome"] == "ok"
    faulty = HorizonsClient(DiskCache(tmp_path / "c"), fault_profile="error", request_log=log, sleep=lambda s: None)
    with pytest.raises(SourceUnavailable):
        faulty.fetch(Q2)
    assert len(log.read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "profile,reason",
    [
        ("down", "network_error"),
        ("error", "http_503"),
        ("empty", "empty_response"),
        ("malformed", "malformed_response"),
        ("timeout", "timeout"),
    ],
)
def test_each_fault_profile_has_its_own_reason(tmp_path, profile, reason):
    faulty = HorizonsClient(DiskCache(tmp_path), fault_profile=profile, sleep=lambda s: None)
    with pytest.raises(SourceUnavailable) as err:
        faulty.fetch(Q1)
    assert err.value.reason == reason


def test_unknown_fault_profile_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        HorizonsClient(DiskCache(tmp_path), fault_profile="flaky")


def test_live_responses_never_land_in_the_fixtures(tmp_path):
    from cielo_bench.domains.astronomy import AstronomyDomain

    domain = AstronomyDomain(fixtures_dir=tmp_path / "fixtures", golden_path=tmp_path / "g.json")
    settings = {"CIELO_CACHE_DIR": str(tmp_path / "live")}
    transport = Recorder(lambda r: httpx.Response(200, content=GOOD))
    live = domain.client(offline=False, settings=settings, transport=transport, min_interval_s=0, sleep=lambda s: None)
    live.fetch(Q1)
    assert list((tmp_path / "live" / "astronomy" / "horizons").glob("*.json.gz"))
    assert (tmp_path / "live" / "astronomy" / "horizons" / "requests.log.jsonl").exists()
    assert not (tmp_path / "fixtures").exists()
    builder = domain.client(
        offline=False,
        settings=settings,
        transport=transport,
        write_fixtures=True,
        min_interval_s=0,
        sleep=lambda s: None,
    )
    builder.fetch(Q2)
    assert len(list((tmp_path / "fixtures").glob("*.json.gz"))) == 1
    # a fixture is visible to a live client without any request
    reader = domain.client(offline=True, settings=settings)
    assert reader.fetch(Q2).from_cache and reader.fetch(Q1).from_cache
