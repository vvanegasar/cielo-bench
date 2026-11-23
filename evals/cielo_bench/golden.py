"""Domain-independent golden-set file format (schema 2), hashing and structural checks.

A golden set is one JSON document::

    {"name", "domain", "version", "schema_version": 2, "created_utc", "description",
     "frames": {pressure: {lang: "... {claim} ..."}}, "tolerances", "premise_rules",
     "definitions", "credits", "fixtures", "pairs": [...], "sha256"}

and each pair is::

    {"pair_id", "template", "lang", "context", "expected_calls": [{"tool", "args"}],
     "facts", "answer": {"kind", "target", "tolerance", "tolerance_mode", "unit", "display"} | null,
     "premises": {"true":  {"value", "display", "questions": {pressure: {"es", "en"}}},
                  "false": {"value", "display", "questions": {pressure: {"es", "en"}}}},
     "sources": [...]}

* ``template`` is the cluster used for clustered intervals.
* ``lang`` is the pair's assigned language (runs use it unless asked for both).
* ``pressure`` is one of ``PRESSURES``: the same claim framed neutrally (a question), as a
  confident assertion, or as an assertion backed by a claimed credential.
* ``answer.kind`` is one of ``domain.ANSWER_KINDS``; ``tolerance_mode`` is ``abs`` (default)
  or ``rel``.

**Schema 3** (a domain whose items vary the data, not the wording: ADR-0009). A pair is one
request about one entity, with one wording, run in several worlds::

    {"pair_id", "template", "lang", "context", "expected_calls", "request": {"tool", "args"},
     "requests": {pressure: {lang: text}}, "insistence": {lang: text},
     "worlds": {world: {"patch", "patch_sha256", "pre_sha256", "facts", ...}}, ...}

Schema 2 files still load. The hash covers everything except ``created_utc`` and ``sha256`` itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import ANSWER_KINDS, TOLERANCE_MODES

SCHEMA_VERSION = 2
WORLDS_SCHEMA_VERSION = 3  # one request, several worlds (ADR-0009)
SCHEMA_VERSIONS = (SCHEMA_VERSION, WORLDS_SCHEMA_VERSION)
PREMISES = ("true", "false")
LANGS = ("es", "en")
PRESSURES = ("neutral", "assertive", "authority")
_VOLATILE = ("created_utc", "sha256")


class GoldenSetError(ValueError):
    pass


def golden_hash(doc: dict[str, Any]) -> str:
    content = {k: v for k, v in doc.items() if k not in _VOLATILE}
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_golden(doc: dict[str, Any], path: Path) -> str:
    doc = dict(doc)
    doc["sha256"] = golden_hash(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(doc["sha256"])


def validate_structure(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if doc.get("schema_version") == WORLDS_SCHEMA_VERSION:
        return validate_worlds_structure(doc)
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be one of {SCHEMA_VERSIONS}")
    pairs = doc.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return [*problems, "golden set has no pairs"]
    seen: set[str] = set()
    for pair in pairs:
        pid = pair.get("pair_id", "?")
        if pid in seen:
            problems.append(f"duplicate pair_id {pid}")
        seen.add(pid)
        for field in ("template", "lang", "premises", "expected_calls"):
            if field not in pair:
                problems.append(f"{pid}: missing {field}")
        if pair.get("lang") not in LANGS:
            problems.append(f"{pid}: lang must be one of {LANGS}")
        premises = pair.get("premises", {})
        for premise in PREMISES:
            questions = premises.get(premise, {}).get("questions", {})
            for pressure in PRESSURES:
                for lang in LANGS:
                    if not questions.get(pressure, {}).get(lang):
                        problems.append(f"{pid}: missing {premise}/{pressure}/{lang} question")
        answer = pair.get("answer")
        if answer is not None:
            if answer.get("kind") not in ANSWER_KINDS:
                problems.append(f"{pid}: unknown answer kind {answer.get('kind')!r}")
            if not isinstance(answer.get("target"), (int, float)):
                problems.append(f"{pid}: answer target must be a number")
            if not isinstance(answer.get("tolerance"), (int, float)):
                problems.append(f"{pid}: answer tolerance must be a number")
            if answer.get("tolerance_mode", "abs") not in TOLERANCE_MODES:
                problems.append(f"{pid}: tolerance_mode must be one of {TOLERANCE_MODES}")
        if not pair.get("expected_calls"):
            problems.append(f"{pid}: no expected tool calls")
    return problems


WORLD_KEYS = ("patch", "patch_sha256", "pre_sha256", "facts")


def validate_worlds_structure(doc: dict[str, Any]) -> list[str]:
    """Structural checks of a schema-3 golden set (one request, several worlds)."""
    problems: list[str] = []
    pairs = doc.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return ["golden set has no pairs"]
    seen: set[str] = set()
    for pair in pairs:
        pid = pair.get("pair_id", "?")
        if pid in seen:
            problems.append(f"duplicate pair_id {pid}")
        seen.add(pid)
        for field in ("template", "lang", "worlds", "request", "requests", "insistence", "expected_calls"):
            if field not in pair:
                problems.append(f"{pid}: missing {field}")
        if pair.get("lang") not in LANGS:
            problems.append(f"{pid}: lang must be one of {LANGS}")
        worlds = pair.get("worlds") or {}
        if not worlds:
            problems.append(f"{pid}: no worlds")
        for world, data in worlds.items():
            missing = [k for k in WORLD_KEYS if k not in (data or {})]
            if missing:
                problems.append(f"{pid}/{world}: missing {missing}")
        for pressure in PRESSURES:
            for lang in LANGS:
                if not (pair.get("requests") or {}).get(pressure, {}).get(lang):
                    problems.append(f"{pid}: missing {pressure}/{lang} request")
        for lang in LANGS:
            if not (pair.get("insistence") or {}).get(lang):
                problems.append(f"{pid}: missing {lang} insistence turn")
    return problems


@dataclass
class GoldenSet:
    doc: dict[str, Any]
    path: Path

    @property
    def sha256(self) -> str:
        return str(self.doc["sha256"])

    @property
    def domain(self) -> str:
        return str(self.doc["domain"])

    @property
    def pairs(self) -> list[dict[str, Any]]:
        return list(self.doc["pairs"])

    @property
    def templates(self) -> list[str]:
        return sorted({p["template"] for p in self.doc["pairs"]})

    def pair(self, pair_id: str) -> dict[str, Any]:
        for pair in self.doc["pairs"]:
            if pair["pair_id"] == pair_id:
                return dict(pair)
        raise KeyError(pair_id)

    @staticmethod
    def question(pair: dict[str, Any], premise: str, pressure: str, lang: str | None = None) -> str:
        return str(pair["premises"][premise]["questions"][pressure][lang or pair["lang"]])


def load_golden(path: Path, *, verify_hash: bool = True) -> GoldenSet:
    if not path.is_file():
        raise GoldenSetError(f"golden set not found: {path} (run `cielo-bench build-golden`)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if verify_hash:
        stored = doc.get("sha256")
        actual = golden_hash(doc)
        if stored != actual:
            raise GoldenSetError(
                f"golden set hash mismatch: stored {stored}, actual {actual}. "
                "It was edited by hand; rebuild it with `cielo-bench build-golden`."
            )
    problems = validate_structure(doc)
    if problems:
        raise GoldenSetError("invalid golden set: " + "; ".join(problems[:5]))
    return GoldenSet(doc=doc, path=path)
