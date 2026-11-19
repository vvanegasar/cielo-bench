"""Content-addressed disk cache for upstream responses (gzip on disk, SHA-256 verified).

Any domain that reads an external source stores the raw response here. An entry whose
bytes no longer match the recorded hash raises ``CacheIntegrityError`` and is never used.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1
SUFFIX = ".json.gz"


class CacheIntegrityError(RuntimeError):
    """A cached response is unreadable or does not match its recorded hash."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def query_key(endpoint: str, query: Mapping[str, str]) -> str:
    """Stable key for a request: the order of the query parameters does not matter."""
    canonical = json.dumps(
        {"endpoint": endpoint, "query": {k: str(query[k]) for k in sorted(query)}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256_hex(canonical.encode("utf-8"))[:24]


@dataclass(frozen=True)
class CachedResponse:
    key: str
    endpoint: str
    query: dict[str, str]
    body: bytes
    sha256: str
    retrieved_at_utc: str
    from_cache: bool = True

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


class DiskCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, key: str) -> Path:
        return self.root / f"{key}{SUFFIX}"

    def keys(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name[: -len(SUFFIX)] for p in self.root.glob(f"*{SUFFIX}"))

    def get(self, key: str) -> CachedResponse | None:
        path = self.path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            body = record["response_text"].encode("utf-8")
            expected = record["response_sha256"]
            stored_key = record["key"]
        except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
            raise CacheIntegrityError(f"unreadable cache entry {path.name}: {exc}") from exc
        if stored_key != key:
            raise CacheIntegrityError(f"cache entry {path.name} is stored under another key")
        if sha256_hex(body) != expected:
            raise CacheIntegrityError(f"hash mismatch for cache entry {path.name}")
        return CachedResponse(
            key=key,
            endpoint=record["endpoint"],
            query=record["query"],
            body=body,
            sha256=expected,
            retrieved_at_utc=record["retrieved_at_utc"],
            from_cache=True,
        )

    def put(
        self, key: str, endpoint: str, query: Mapping[str, str], body: bytes, retrieved_at_utc: str
    ) -> CachedResponse:
        self.root.mkdir(parents=True, exist_ok=True)
        digest = sha256_hex(body)
        record = {
            "schema": SCHEMA,
            "key": key,
            "endpoint": endpoint,
            "query": {k: str(query[k]) for k in sorted(query)},
            "retrieved_at_utc": retrieved_at_utc,
            "response_sha256": digest,
            "response_bytes": len(body),
            "response_text": body.decode("utf-8"),
        }
        data = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        path = self.path(key)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(gzip.compress(data, mtime=0))  # mtime=0: identical bytes for identical data
        tmp.replace(path)
        return CachedResponse(
            key=key,
            endpoint=endpoint,
            query=dict(record["query"]),
            body=body,
            sha256=digest,
            retrieved_at_utc=retrieved_at_utc,
            from_cache=False,
        )


class LayeredCache:
    """Read through several caches in order; write to one.

    Used to keep the golden set's frozen fixtures read-only: live responses (a real run, the
    MCP server in live mode) are written to a separate cache directory, never to the fixtures.
    """

    def __init__(self, read: list[DiskCache], write: DiskCache):
        self.read_layers = list(read)
        self.write_layer = write

    @property
    def root(self) -> Path:
        return self.write_layer.root

    def keys(self) -> list[str]:
        return sorted(set().union(*(layer.keys() for layer in self.read_layers)))

    def get(self, key: str) -> CachedResponse | None:
        for layer in self.read_layers:
            hit = layer.get(key)
            if hit is not None:
                return hit
        return None

    def put(
        self, key: str, endpoint: str, query: Mapping[str, str], body: bytes, retrieved_at_utc: str
    ) -> CachedResponse:
        return self.write_layer.put(key, endpoint, query, body, retrieved_at_utc)
