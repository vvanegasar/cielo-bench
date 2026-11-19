"""NASA/JPL Horizons API client: serialized, cached, hashed and honest about failure.

JPL SSD fair-use policy: one request at a time, cache results, identify the client with a
User-Agent. This client:

* serializes every live request in the process behind one lock and spaces them out;
* caches each raw response on disk under a key derived from the normalized query, with
  the SHA-256 of the response bytes (``cielo_bench.cache``);
* never invents data: any failure (timeout, network error, HTTP error, malformed or empty
  response, cache integrity error, offline cache miss, request cap) raises
  ``SourceUnavailable`` and the tool layer turns it into ``status: source_unavailable``;
* supports fault profiles that simulate an outage. Under a fault profile the cache is
  bypassed on purpose, so the whole failure path runs end to end.
"""

from __future__ import annotations

import json
import ssl
import threading
import time as _time
from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path

import httpx

from ...cache import CachedResponse, CacheIntegrityError, DiskCache, LayeredCache, query_key
from ...config import DEFAULT_USER_AGENT
from ...domain import BUDGET_EXHAUSTED
from ...net import ssl_context
from .sky import BODIES, UTC, City

ENDPOINT = "https://ssd.jpl.nasa.gov/api/horizons.api"
SERVICE = "NASA/JPL Horizons API"
CREDIT = "NASA/JPL Solar System Dynamics — Horizons (https://ssd.jpl.nasa.gov/horizons/)"
# down / error / empty are the generic fault kinds (cielo_bench.domain.FAULT_KINDS);
# malformed and timeout are extra profiles for tests and robustness checks.
FAULT_PROFILES = ("down", "error", "empty", "malformed", "timeout")
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
EMPTY_TABLE_RESULT = "Ephemeris (simulated empty answer)\n$$SOE\n$$EOE\n"


class SourceUnavailable(Exception):
    """The upstream source could not provide valid data. Nothing may be invented."""

    def __init__(self, reason: str, detail: str = "", source: str = SERVICE):
        super().__init__(f"{source} unavailable: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail
        self.source = source


def day_table_query(body: str, city: City, local_date: date) -> dict[str, str]:
    """One observer table per (body, city, local calendar date), 1-minute steps.

    The table spans local midnight to the next local midnight (1441 rows), so every
    whole-minute position on that date is an exact Horizons value and rise, set and
    culmination can be read from the same table without extra requests.
    """
    start = datetime.combine(local_date, time(0, 0), tzinfo=city.tz).astimezone(UTC)
    stop = start + timedelta(days=1)
    return {
        "format": "json",
        "COMMAND": f"'{BODIES[body]}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{city.lon:.4f},{city.lat:.4f},{city.elevation_m / 1000:.3f}'",
        "START_TIME": f"'{start:%Y-%m-%d %H:%M}'",
        "STOP_TIME": f"'{stop:%Y-%m-%d %H:%M}'",
        "STEP_SIZE": "'1 m'",
        "QUANTITIES": "'1,4,20'",
        "APPARENT": "'REFRACTED'",
        "CSV_FORMAT": "'YES'",
        "ANG_FORMAT": "'DEG'",
        "TIME_DIGITS": "'MINUTES'",
    }


# One hourly Moon-phase table per city covers every date in the golden-set plan.
PHASE_WINDOW = ("2026-12-11 00:00", "2027-03-22 00:00")  # UTC


def moon_phase_query(city: City, start_utc: str = PHASE_WINDOW[0], stop_utc: str = PHASE_WINDOW[1]) -> dict[str, str]:
    """Hourly illuminated fraction of the Moon (quantity 10) and Sun-Observer-Target elongation with
    its leading/trailing flag (quantity 23), as seen from the city."""
    return {
        "format": "json",
        "COMMAND": "'301'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{city.lon:.4f},{city.lat:.4f},{city.elevation_m / 1000:.3f}'",
        "START_TIME": f"'{start_utc}'",
        "STOP_TIME": f"'{stop_utc}'",
        "STEP_SIZE": "'1 h'",
        "QUANTITIES": "'10,23'",
        "CSV_FORMAT": "'YES'",
        "ANG_FORMAT": "'DEG'",
        "TIME_DIGITS": "'MINUTES'",
    }


class _FaultTransport(httpx.BaseTransport):
    """Simulated outage used by the tool_fault condition and by the tests."""

    def __init__(self, profile: str):
        if profile not in FAULT_PROFILES:
            raise ValueError(f"unknown fault profile {profile!r}; choose from {FAULT_PROFILES}")
        self.profile = profile

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.profile == "down":
            raise httpx.ConnectError("simulated: connection refused (fault profile down)", request=request)
        if self.profile == "timeout":
            raise httpx.ReadTimeout("simulated timeout (fault profile timeout)", request=request)
        if self.profile == "error":
            return httpx.Response(503, text="Service Unavailable (simulated)", request=request)
        if self.profile == "empty":
            body = json.dumps({"signature": {"source": SERVICE, "version": "1.2"}, "result": EMPTY_TABLE_RESULT})
            return httpx.Response(200, text=body, request=request)
        return httpx.Response(200, text="<html>simulated malformed body</html>", request=request)


class _Malformed(Exception):
    def __init__(self, reason: str, detail: str, retryable: bool):
        super().__init__(detail)
        self.reason, self.detail, self.retryable = reason, detail, retryable


def _validate_body(body: bytes) -> None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _Malformed("malformed_response", f"body is not JSON: {exc}", retryable=True) from exc
    if not isinstance(payload, dict):
        raise _Malformed("malformed_response", "JSON body is not an object", retryable=True)
    if payload.get("error"):
        raise _Malformed("upstream_error", str(payload["error"])[:300], retryable=False)
    result = payload.get("result")
    if not isinstance(result, str):
        raise _Malformed("malformed_response", "no 'result' text in response", retryable=True)
    if "$$SOE" not in result or "$$EOE" not in result:
        raise _Malformed("no_ephemeris", "response has no $$SOE/$$EOE table", retryable=False)
    table = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    if not table.strip():
        raise _Malformed("empty_response", "the ephemeris table has no rows", retryable=False)


class HorizonsClient:
    _request_lock = threading.Lock()  # one live request in flight per process
    _last_request_monotonic = 0.0

    def __init__(
        self,
        cache: DiskCache | LayeredCache,
        *,
        transport: httpx.BaseTransport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = 60.0,
        retries: int = 2,
        backoff_s: float = 2.0,
        min_interval_s: float = 1.0,
        offline: bool = False,
        max_live_requests: int | None = None,
        fault_profile: str | None = None,
        request_log: Path | None = None,
        sleep: Callable[[float], None] = _time.sleep,
        verify: ssl.SSLContext | None = None,
    ):
        self.cache = cache
        self.fault_profile = fault_profile or None
        if self.fault_profile is not None:
            transport = _FaultTransport(self.fault_profile)
        self.offline = offline
        self.retries = retries
        self.backoff_s = backoff_s if self.fault_profile is None else 0.0
        self.min_interval_s = min_interval_s if self.fault_profile is None else 0.0
        self.max_live_requests = max_live_requests
        self.request_log = request_log
        self.user_agent = user_agent
        self._sleep = sleep
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout_s,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
            verify=verify or ssl_context(),
        )
        self.live_requests = 0
        self._count_lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ public API
    def fetch(self, query: Mapping[str, str]) -> CachedResponse:
        key = query_key(ENDPOINT, query)
        if self.fault_profile is not None:
            # Simulated outage: skip the cache so the failure path is exercised end to end.
            with self._request_lock:
                self._request(query, key)  # always raises for the fault transports
            raise SourceUnavailable("unexpected_success_under_fault", self.fault_profile)
        cached = self._cached(key)
        if cached is not None:
            return cached
        if self.offline:
            raise SourceUnavailable("offline_cache_miss", f"no cached response for key {key}")
        with self._request_lock:
            cached = self._cached(key)  # another thread may have fetched it while we waited
            if cached is not None:
                return cached
            with self._count_lock:
                if self.max_live_requests is not None and self.live_requests >= self.max_live_requests:
                    raise SourceUnavailable(BUDGET_EXHAUSTED, f"cap of {self.max_live_requests} live requests")
                self.live_requests += 1
            body, retrieved_at = self._request(query, key)
            return self.cache.put(key, ENDPOINT, query, body, retrieved_at)

    # ------------------------------------------------------------------ internals
    def _cached(self, key: str) -> CachedResponse | None:
        try:
            return self.cache.get(key)
        except CacheIntegrityError as exc:
            raise SourceUnavailable("cache_integrity_error", str(exc)) from exc

    def _polite_wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        elapsed = _time.monotonic() - HorizonsClient._last_request_monotonic
        if elapsed < self.min_interval_s:
            self._sleep(self.min_interval_s - elapsed)

    def _request(self, query: Mapping[str, str], key: str) -> tuple[bytes, str]:
        reason, detail = "unknown", ""
        for attempt in range(self.retries + 1):
            if attempt and self.backoff_s > 0:
                self._sleep(self.backoff_s * 2 ** (attempt - 1))
            self._polite_wait()
            started = datetime.now(UTC)
            t0 = _time.monotonic()
            try:
                response = self._http.get(ENDPOINT, params=dict(query))
            except httpx.TimeoutException as exc:
                reason, detail = "timeout", str(exc)
                self._log(key, attempt, None, 0, _time.monotonic() - t0, reason)
                continue
            except httpx.TransportError as exc:
                reason, detail = "network_error", str(exc)
                self._log(key, attempt, None, 0, _time.monotonic() - t0, reason)
                continue
            finally:
                if self.fault_profile is None:
                    HorizonsClient._last_request_monotonic = _time.monotonic()
            elapsed = _time.monotonic() - t0
            status = response.status_code
            if status in RETRYABLE_STATUS:
                reason, detail = f"http_{status}", response.text[:200]
                self._log(key, attempt, status, len(response.content), elapsed, reason)
                continue
            if status != 200:
                self._log(key, attempt, status, len(response.content), elapsed, f"http_{status}")
                raise SourceUnavailable(f"http_{status}", response.text[:200])
            try:
                _validate_body(response.content)
            except _Malformed as exc:
                reason, detail = exc.reason, exc.detail
                self._log(key, attempt, status, len(response.content), elapsed, reason)
                if exc.retryable:
                    continue
                raise SourceUnavailable(exc.reason, exc.detail) from exc
            self._log(key, attempt, status, len(response.content), elapsed, "ok")
            return response.content, started.isoformat(timespec="seconds").replace("+00:00", "Z")
        raise SourceUnavailable(reason, detail)

    def _log(self, key: str, attempt: int, status: int | None, size: int, elapsed: float, outcome: str) -> None:
        if self.request_log is None or self.fault_profile is not None:
            return
        entry = {
            "at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "key": key,
            "attempt": attempt,
            "http_status": status,
            "bytes": size,
            "elapsed_s": round(elapsed, 3),
            "outcome": outcome,
            "user_agent": self.user_agent,
        }
        self.request_log.parent.mkdir(parents=True, exist_ok=True)
        with self.request_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
