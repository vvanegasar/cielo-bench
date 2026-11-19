import gzip
import json

import pytest

from cielo_bench.cache import CacheIntegrityError, DiskCache, query_key, sha256_hex


def test_roundtrip_records_hash_and_flags(tmp_path):
    cache = DiskCache(tmp_path)
    stored = cache.put(
        "k1", "https://example.test/api", {"b": "2", "a": "1"}, b'{"result": "x"}', "2026-11-18T00:00:00Z"
    )
    assert stored.from_cache is False
    loaded = cache.get("k1")
    assert loaded.from_cache is True
    assert loaded.body == b'{"result": "x"}'
    assert loaded.sha256 == sha256_hex(b'{"result": "x"}')
    assert loaded.query == {"a": "1", "b": "2"}
    assert cache.keys() == ["k1"]


def test_missing_entry_is_none(tmp_path):
    assert DiskCache(tmp_path).get("nope") is None


def test_query_key_ignores_parameter_order():
    a = query_key("e", {"COMMAND": "'699'", "STEP_SIZE": "'1 m'"})
    b = query_key("e", {"STEP_SIZE": "'1 m'", "COMMAND": "'699'"})
    assert a == b
    assert a != query_key("e", {"COMMAND": "'599'", "STEP_SIZE": "'1 m'"})


def test_tampered_entry_is_rejected(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("k1", "e", {}, b'{"result": "original"}', "t")
    path = cache.path("k1")
    record = json.loads(gzip.decompress(path.read_bytes()))
    record["response_text"] = '{"result": "tampered"}'
    path.write_bytes(gzip.compress(json.dumps(record).encode()))
    with pytest.raises(CacheIntegrityError):
        cache.get("k1")


def test_corrupt_file_is_rejected(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("k1", "e", {}, b"{}", "t")
    cache.path("k1").write_bytes(b"not gzip at all")
    with pytest.raises(CacheIntegrityError):
        cache.get("k1")


def test_identical_content_gives_identical_bytes(tmp_path):
    a, b = DiskCache(tmp_path / "a"), DiskCache(tmp_path / "b")
    a.put("k", "e", {"q": "1"}, b"{}", "t")
    b.put("k", "e", {"q": "1"}, b"{}", "t")
    assert a.path("k").read_bytes() == b.path("k").read_bytes()


def test_layered_cache_reads_through_and_writes_to_one_layer(tmp_path):
    from cielo_bench.cache import LayeredCache

    fixtures, live = DiskCache(tmp_path / "fixtures"), DiskCache(tmp_path / "live")
    fixtures.put("frozen", "e", {}, b"{}", "t")
    layered = LayeredCache([fixtures, live], live)
    assert layered.get("frozen").body == b"{}" and layered.get("missing") is None
    layered.put("new", "e", {}, b"[]", "t")
    assert live.get("new") is not None and fixtures.get("new") is None
    assert layered.keys() == ["frozen", "new"] and layered.root == live.root


def test_live_cache_dir_resolution(tmp_path, monkeypatch):
    from cielo_bench.config import live_cache_dir

    monkeypatch.delenv("CIELO_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert live_cache_dir() == tmp_path / "xdg" / "cielo-bench"
    monkeypatch.setenv("CIELO_CACHE_DIR", str(tmp_path / "env"))
    assert live_cache_dir() == tmp_path / "env"
    assert live_cache_dir({"CIELO_CACHE_DIR": str(tmp_path / "settings")}) == tmp_path / "settings"
    monkeypatch.delenv("CIELO_CACHE_DIR")
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert live_cache_dir().parts[-2:] == (".cache", "cielo-bench")
