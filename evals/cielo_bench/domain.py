"""The domain interface.

A *domain* is one kind of verifiable question. It supplies four things:

1. an **item generator** that writes a golden set of premise pairs (the same question with
   a true and a false user premise), grouped by template (the cluster for statistics);
2. the **tools** the agent may call, and an executor that runs them (with a fault profile
   that simulates the source being down);
3. the **ground truth and tolerances**: the rule that decides whether a premise holds;
4. how to read **evidence** back out of a tool trace.

The runner, the providers, the scorer, the statistics and the report only talk to this
interface. Adding a domain means adding a package under ``cielo_bench/domains/`` and
registering it in ``cielo_bench/domains/__init__.py``; nothing else changes.

Tool results follow one contract in every domain: a JSON object with ``status`` in
``ok | invalid_input | source_unavailable | out_of_scope``. A non-``ok`` result carries no
values (no partial, invented data). ``reason == "request_budget_exhausted"`` marks a result
caused by the harness's own request cap; the scorer excludes those trials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

TOOL_STATUSES = ("ok", "invalid_input", "source_unavailable", "out_of_scope")
BUDGET_EXHAUSTED = "request_budget_exhausted"
# Every ok result cites its sources: a non-empty "sources" list whose items name these fields.
CITATION_FIELDS = ("service", "query", "retrieved_at_utc")
# A non-ok result carries no values: only these keys are allowed.
FAILURE_KEYS = frozenset({"status", "source", "reason", "message"})

# Fault kinds every domain must support as fault profiles (``make_executor(fault_profile=...)``):
#   down  - the source cannot be reached (connection refused / timeout)
#   error - the source answers with an error (for example HTTP 5xx)
#   empty - the source answers successfully but with no data
# In all three the executor returns status "source_unavailable" with a reason and no values.
# Domains may add extra profiles (for example "malformed").
FAULT_KINDS = ("down", "error", "empty")

# Kinds of numeric answer the generic scorer knows how to parse and compare.
ANSWER_KINDS = ("angle_deg", "clock_time", "number")
# How an answer's tolerance is applied: absolute |reported - target| <= tolerance, or
# relative |reported - target| <= tolerance * |target| (for amounts, e.g. revenue).
TOLERANCE_MODES = ("abs", "rel")


def contract_problems(result: Any) -> list[str]:
    """Problems with a tool result under the shared contract; an empty list means it complies.

    * ``status`` is one of ``TOOL_STATUSES``;
    * an ``ok`` result has a non-empty ``sources`` list, and every source names
      ``service``, ``query`` and ``retrieved_at_utc``;
    * any other result carries no values (only ``FAILURE_KEYS``).
    """
    if not isinstance(result, dict):
        return [f"a tool result must be a JSON object, got {type(result).__name__}"]
    status = result.get("status")
    if status not in TOOL_STATUSES:
        return [f"unknown status {status!r}"]
    if status != "ok":
        extra = sorted(set(result) - FAILURE_KEYS)
        return [f"a {status} result must carry no values, found {extra}"] if extra else []
    sources = result.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["an ok result must have a non-empty sources list"]
    problems = []
    for i, source in enumerate(sources):
        missing = [f for f in CITATION_FIELDS if not (isinstance(source, dict) and source.get(f))]
        if missing:
            problems.append(f"sources[{i}] lacks {missing}")
    return problems


@dataclass(frozen=True)
class ToolEvent:
    """One tool call in a trial: what the model asked for and what it got back."""

    name: str
    arguments: dict[str, Any] | None
    result: dict[str, Any]


@dataclass(frozen=True)
class Evidence:
    """What a trial's tool calls established about a pair.

    attempted: every expected call was made with matching arguments (whatever the outcome).
    obtained:  every one of those calls returned status ``ok``.
    facts:     ground-truth-shaped facts read from those results (only when obtained).
    """

    attempted: bool
    obtained: bool
    facts: dict[str, Any] | None = None


class ToolExecutor(Protocol):
    live_requests: int

    def execute(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]: ...


class Domain(ABC):
    name: str = ""
    title: str = ""
    credits: tuple[str, ...] = ()
    fault_profiles: tuple[str, ...] = ()
    default_fault_profile: str = ""
    # Whether the tools may reach a service outside this machine (when allowed to go live).
    # Astronomy: True (NASA/JPL Horizons). A domain on a local, synthetic snapshot: False.
    # The MCP server uses it for openWorldHint.
    external_source: bool = True
    # False for item banks with a design of their own (the distance ladder): the standard validation with
    # simulated agents, the power table and the README tables do not apply to them.
    standard_design: bool = True

    # --- 1. item generator and golden set -------------------------------------------
    @property
    @abstractmethod
    def golden_path(self) -> Path:
        """Where this domain's golden set lives."""

    @abstractmethod
    def build_golden(
        self, *, offline: bool = False, max_requests: int | None = None, settings: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        """Generate the golden set document (pairs, ground truth, sources)."""

    @abstractmethod
    def verify_golden(self, golden: Any) -> list[str]:
        """Domain checks of a loaded golden set. Returns a list of problems (empty = ok)."""

    # --- 2. tools ---------------------------------------------------------------------
    @abstractmethod
    def system_preamble(self, lang: str) -> str:
        """Role text for the system prompt. The harness appends the answer format."""

    @abstractmethod
    def tool_specs(self) -> list[dict[str, Any]]:
        """Provider-neutral tool definitions: name, description, JSON-schema parameters."""

    @abstractmethod
    def make_executor(
        self,
        *,
        fault_profile: str | None = None,
        offline: bool = True,
        max_live_requests: int | None = None,
        settings: Mapping[str, str] | None = None,
    ) -> ToolExecutor:
        """Executor for the tools. With a fault profile, the source behaves as down."""

    # --- 3. ground truth and tolerances ----------------------------------------------
    @abstractmethod
    def premise_holds(self, pair: Mapping[str, Any], premise_value: Any, facts: Mapping[str, Any]) -> bool | None:
        """True or False if the premise holds given the facts; None if it is ambiguous."""

    # --- 4. evidence ------------------------------------------------------------------
    @abstractmethod
    def evidence(self, pair: Mapping[str, Any], trace: list[ToolEvent]) -> Evidence:
        """Match a trial's tool calls against the pair's expected calls."""

    def value_examples(self, lang: str) -> tuple[str, ...]:
        """Examples for the answer-format line ``VALUE: <number>`` in the system prompt.

        Optional. Override with values that look like this domain's answers (for example
        ``("35°", "19:40")`` or ``("$1,234,567.89", "42")``)."""
        return ("42",)

    def value_from_facts(self, pair: Mapping[str, Any], facts: Mapping[str, Any]) -> float | None:
        """The numeric answer implied by the facts (None if the pair has no numeric answer)."""
        return None

    def perturb_call(self, call: Mapping[str, Any]) -> dict[str, Any] | None:
        """Optional: a plausible *wrong* version of an expected call (used by the simulator)."""
        return None
