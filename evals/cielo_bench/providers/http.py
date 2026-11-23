"""HTTP plumbing shared by the real providers: retries, rate limiting and an output cache.

* ``post_json`` retries transient failures (408, 409, 429, 5xx, 529, the 520-524 errors of a
  CDN in front of the API, timeouts, network errors) with exponential backoff and honours
  ``Retry-After``. Headers are never logged.
* ``RateLimiter`` spaces requests to at most N per minute, across threads.
* ``ResponseCache`` stores each raw response under the SHA-256 of (url, body, salt). The
  runner salts with the trial id and round, so a resumed run replays finished rounds for
  free while repetitions of the same question stay independent.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .base import ProviderError

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529}


class RateLimiter:
    def __init__(
        self,
        requests_per_minute: float | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._clock, self._sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request may be sent. Returns the seconds waited."""
        if self.interval <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if wait:
            self._sleep(wait)
        return wait


class ResponseCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    @staticmethod
    def key(url: str, body: dict[str, Any], salt: str) -> str:
        canonical = json.dumps(
            {"url": url, "body": body, "salt": salt}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # a broken cache entry is simply a miss

    def put(self, key: str, data: dict[str, Any]) -> None:
        path = self._path(key)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)


def post_json(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    max_attempts: int = 6,
    base_delay_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    limiter: RateLimiter | None = None,
) -> tuple[dict[str, Any], float]:
    last = "no attempt made"
    for attempt in range(1, max_attempts + 1):
        if limiter is not None:
            limiter.acquire()
        t0 = time.monotonic()
        try:
            response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            last = f"timeout: {exc}"
        except httpx.TransportError as exc:
            last = f"network error: {exc}"
        else:
            elapsed = time.monotonic() - t0
            if response.status_code == 200:
                try:
                    return response.json(), elapsed
                except ValueError as exc:
                    raise ProviderError(f"response is not JSON: {exc}", status=200) from exc
            if response.status_code not in RETRYABLE:
                raise ProviderError(f"HTTP {response.status_code}: {response.text[:500]}", status=response.status_code)
            last = f"HTTP {response.status_code}: {response.text[:200]}"
            retry_after = response.headers.get("retry-after")
            if retry_after and attempt < max_attempts:
                try:
                    sleep(min(float(retry_after), 60.0))
                    continue
                except ValueError:
                    pass
        if attempt < max_attempts:
            sleep(base_delay_s * 2 ** (attempt - 1))
    raise ProviderError(f"gave up after {max_attempts} attempts ({last})", retryable=True)


class HTTPProviderMixin:
    """Common request path for the real providers: cache lookup, rate limit, retries."""

    cache: ResponseCache | None = None
    limiter: RateLimiter | None = None
    _http: httpx.Client
    _sleep: Callable[[float], None]

    def _send(
        self, url: str, headers: dict[str, str], body: dict[str, Any], salt: str
    ) -> tuple[dict[str, Any], float, bool]:
        key = ResponseCache.key(url, body, salt) if self.cache is not None else ""
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached, 0.0, True
        data, latency = post_json(self._http, url, headers, body, sleep=self._sleep, limiter=self.limiter)
        if self.cache is not None:
            self.cache.put(key, data)
        return data, latency, False
