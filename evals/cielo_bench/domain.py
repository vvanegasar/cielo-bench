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
    """One tool call in a trial: what the model asked for and what it got back.

    ``turn`` is the user turn the call belongs to (1 in a single-turn trial) and ``round`` the
    index of the model round, counted across the whole trial. Single-turn domains can ignore both.
    """

    name: str
    arguments: dict[str, Any] | None
    result: dict[str, Any]
    turn: int = 1
    round: int = 0


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


@dataclass(frozen=True)
class TrialContext:
    """Who and what one trial is, for a domain that opens a sandbox per trial.

    ``premise`` is the planned premise; in a domain whose items vary the world instead of the
    wording it names the world (``Domain.premises``). ``world_free_id`` is the trial id with the
    premise left out, so the trials of one unit in different worlds share it.
    """

    trial_id: str
    world_free_id: str
    model_label: str
    pair_id: str
    premise: str
    pressure: str
    condition: str
    lang: str
    rep: int


class TrialSandbox(Protocol):
    """A per-trial environment (``Domain.open_trial``): its own executor and a record of the trial.

    ``end_turn(turn)`` is called when the agent loop finishes a user turn. It returns the text of
    the next user turn, or None to end the trial. ``record()`` is stored with the trial, and
    ``close()`` releases the sandbox.
    """

    executor: ToolExecutor

    def end_turn(self, turn: int) -> str | None: ...

    def record(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


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

    # --- 5. optional hooks for other designs ----------------------------------------
    # The defaults below are the question-answering design of the first domains: the runner's
    # conditions and premises, one executor per condition, one user turn, the answer format in
    # the system prompt and the shared scorer. A domain overrides only what it changes.

    # The run's reasoning effort, sent explicitly to every model and recorded in the manifest.
    # None: no effort is sent (each model runs at its API default).
    effort: str | None = None
    # Order the pairs of a run round-robin over templates, so a budget stop cuts every template
    # about equally (the default keeps the golden set's order).
    interleave_templates: bool = False
    # Which report the run gets: "answer" (the shared report) or the domain's own kind.
    report_kind: str = "answer"

    def conditions(self) -> tuple[str, ...] | None:
        """The conditions this domain runs, or None for the runner's default conditions."""
        return None

    def premises(self) -> tuple[str, ...] | None:
        """The premise levels this domain runs (worlds, in a domain that varies the data), or None
        for the runner's default ``true`` and ``false``."""
        return None

    def premises_for(self, condition: str, premises: tuple[str, ...]) -> tuple[str, ...]:
        """The premise levels at which ``condition`` runs. A condition whose inputs do not depend on
        the premise can run once per unit, under a premise of its own (for example ``any``)."""
        return premises

    def tools_for(self, condition: str) -> list[dict[str, Any]] | None:
        """Tool definitions offered in ``condition`` (None: no tools are sent)."""
        return None if condition == "no_tool" else self.tool_specs()

    def answer_mode(self, condition: str) -> bool:
        """Whether the system prompt of ``condition`` ends with the shared answer format."""
        return True

    def trial_text(self, pair: Mapping[str, Any], ctx: TrialContext) -> str | None:
        """The first user turn of a trial, or None for the golden set's question."""
        return None

    def round_caps(self, condition: str) -> tuple[int, ...] | None:
        """Tool rounds allowed per user turn, or None for the agent loop's default (one turn)."""
        return None

    def open_trial(self, pair: Mapping[str, Any], ctx: TrialContext) -> TrialSandbox | None:
        """A sandbox for one trial, with its own executor, or None to use the run's executor for the
        trial's condition (``make_executor``)."""
        return None

    def make_simulator(self, persona: str, golden: Any, seed: int) -> Any:
        """A simulated model for this domain, or None for the shared simulated provider."""
        return None
