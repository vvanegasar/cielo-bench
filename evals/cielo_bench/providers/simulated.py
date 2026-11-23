"""Deterministic simulated model for dry runs and tests. It is NOT a language model.

It looks the question up in the golden set (an oracle), then behaves according to a
persona: how often it calls the tool, how often it caves to a false premise after seeing
contrary evidence, how often it refuses when the source is down, and so on. Every random
decision is a hash of (seed, model, trial id, decision), so a run is reproducible bit for
bit. It goes through the same agent loop, tools, scorer and report as a real model, and
it only uses the domain interface, so it works for any domain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from ..domain import Domain, ToolEvent
from ..golden import GoldenSet
from ..scoring import format_value, premise_number
from .base import Conversation, Provider, ToolCall, Turn, Usage


@dataclass(frozen=True)
class Persona:
    name: str
    p_call_tool: float  # calls the expected tool(s) when tools are offered
    p_wrong_args: float  # ...with perturbed arguments (the evidence will not match)
    p_agree_after_check: float  # agrees with a false premise after contrary evidence
    p_overcorrect: float  # rejects a true premise after supporting evidence
    p_agree_false_no_tool: float  # agrees with a false premise without evidence
    p_reject_false_no_tool: float  # otherwise says FALSE (else UNKNOWN), without evidence
    p_agree_true_no_tool: float  # agrees with a true premise without evidence (else UNKNOWN)
    p_refuse_fault: float  # UNKNOWN and no value when the source is down
    p_agree_fault: float  # when not refusing under a fault: agrees with the premise
    p_format_error: float  # omits the VERDICT line
    # Multipliers on every "agree with a false premise" probability, by pressure level, and on
    # the probability of calling the tool. They make pressure effects visible in dry runs.
    agree_by_pressure: tuple[tuple[str, float], ...] = (("neutral", 0.6), ("assertive", 1.0), ("authority", 1.4))
    call_by_pressure: tuple[tuple[str, float], ...] = (("neutral", 1.0), ("assertive", 1.0), ("authority", 1.0))

    def agree_factor(self, pressure: str) -> float:
        return dict(self.agree_by_pressure).get(pressure, 1.0)

    def call_factor(self, pressure: str) -> float:
        return dict(self.call_by_pressure).get(pressure, 1.0)


PERSONAS = {
    "careful": Persona("careful", 0.95, 0.03, 0.05, 0.03, 0.25, 0.45, 0.60, 0.90, 0.50, 0.01),
    "agreeable": Persona(
        "agreeable",
        0.70,
        0.05,
        0.35,
        0.01,
        0.55,
        0.30,
        0.85,
        0.40,
        0.70,
        0.02,
        agree_by_pressure=(("neutral", 0.5), ("assertive", 1.0), ("authority", 1.5)),
        call_by_pressure=(("neutral", 1.0), ("assertive", 0.95), ("authority", 0.8)),
    ),
}

TEXT = {
    "checked_true": {
        "en": "I checked with the tool: yes, that is right.",
        "es": "Lo verifiqué con la herramienta: sí, es correcto.",
    },
    "checked_false": {
        "en": "I checked with the tool: that is not right.",
        "es": "Lo verifiqué con la herramienta: no es correcto.",
    },
    "caved": {"en": "You are right.", "es": "Tienes razón."},
    "unavailable": {
        "en": "The data source is unavailable right now, so I cannot verify it.",
        "es": "La fuente de datos no está disponible ahora, así que no puedo verificarlo.",
    },
    "guess_true": {"en": "Yes, that sounds right.", "es": "Sí, suena correcto."},
    "guess_false": {"en": "I don't think that is right.", "es": "No creo que sea correcto."},
    "unknown": {"en": "I cannot verify that without data.", "es": "No puedo verificarlo sin datos."},
}


def sent_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The part of each tool definition a model receives: name, description and schema (not, for
    example, MCP annotations). The simulated token counts use it."""
    return [{k: t[k] for k in ("name", "description", "parameters") if k in t} for t in tools or []]


class SimulatedProvider(Provider):
    provider = "simulated"
    simulated = True

    def __init__(self, persona: str, domain: Domain, golden: GoldenSet, seed: int = 0):
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}; choose from {sorted(PERSONAS)}")
        super().__init__(f"sim-{persona}-v1", label=f"sim:{persona}")
        self.persona = PERSONAS[persona]
        self.domain = domain
        self.seed = seed
        self._index: dict[str, tuple[dict[str, Any], str, str, str]] = {}
        for pair in golden.pairs:
            for premise in ("true", "false"):
                for pressure, by_lang in pair["premises"][premise]["questions"].items():
                    for lang, question in by_lang.items():
                        self._index[question] = (pair, premise, pressure, lang)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "persona": asdict(self.persona), "seed": self.seed}

    def _u(self, conv: Conversation, decision: str) -> float:
        digest = hashlib.sha256(f"{self.seed}|{self.model}|{conv.trial_id}|{decision}".encode()).hexdigest()
        return int(digest[:13], 16) / 16**13

    # ------------------------------------------------------------------ answers
    def _reply(
        self, conv: Conversation, lang: str, key: str, verdict: str, value: float | None, kind: str | None
    ) -> str:
        lines = [TEXT[key][lang]]
        if self._u(conv, "format") >= self.persona.p_format_error:
            lines.append(f"VERDICT: {verdict}")
        if value is not None and kind:
            lines.append(f"VALUE: {format_value(kind, value)}")
        return "\n".join(lines)

    def _guess(self, conv: Conversation, pair: dict[str, Any]) -> float | None:
        """A wrong number: 3 to 10 tolerances away from the truth, in the answer's own tolerance
        mode (relative for amounts, absolute for angles and clock times), so a guess never lands
        inside the tolerance by luck."""
        answer = pair.get("answer")
        if not answer:
            return None
        target, tolerance = float(answer["target"]), float(answer["tolerance"])
        relative = answer.get("tolerance_mode", "abs") == "rel"
        width = max(tolerance * abs(target), tolerance) if relative else tolerance
        offset = (3.0 + 7.0 * self._u(conv, "guess_size")) * width
        value = target + (offset if self._u(conv, "guess_sign") < 0.5 else -offset)
        return value % 1440.0 if answer["kind"] == "clock_time" else value

    def _without_evidence(
        self, conv: Conversation, pair: dict[str, Any], premise: str, pressure: str, lang: str
    ) -> str:
        p, kind = self.persona, (pair.get("answer") or {}).get("kind")
        if premise == "true":
            if self._u(conv, "agree_true") < p.p_agree_true_no_tool:
                return self._reply(conv, lang, "guess_true", "TRUE", premise_number(pair, premise), kind)
            return self._reply(conv, lang, "unknown", "UNKNOWN", None, kind)
        if self._u(conv, "agree_false") < min(0.95, p.p_agree_false_no_tool * p.agree_factor(pressure)):
            return self._reply(conv, lang, "guess_true", "TRUE", premise_number(pair, premise), kind)
        if self._u(conv, "reject_false") < p.p_reject_false_no_tool:
            return self._reply(conv, lang, "guess_false", "FALSE", self._guess(conv, pair), kind)
        return self._reply(conv, lang, "unknown", "UNKNOWN", None, kind)

    def _after_tools(self, conv: Conversation, pair: dict[str, Any], premise: str, pressure: str, lang: str) -> str:
        p, kind = self.persona, (pair.get("answer") or {}).get("kind")
        trace = [
            ToolEvent(e["name"], e["arguments"], e["result"])
            for msg in conv.messages
            if msg.get("role") == "tool_results"
            for e in msg["events"]
        ]
        evidence = self.domain.evidence(pair, trace)
        if evidence.obtained and evidence.facts is not None:
            holds = self.domain.premise_holds(pair, pair["premises"][premise]["value"], evidence.facts)
            value = self.domain.value_from_facts(pair, evidence.facts)
            if holds is True:
                if self._u(conv, "overcorrect") < p.p_overcorrect:
                    return self._reply(conv, lang, "checked_false", "FALSE", value, kind)
                return self._reply(conv, lang, "checked_true", "TRUE", value, kind)
            if holds is False:
                if self._u(conv, "cave") < min(0.95, p.p_agree_after_check * p.agree_factor(pressure)):
                    return self._reply(conv, lang, "caved", "TRUE", premise_number(pair, premise), kind)
                return self._reply(conv, lang, "checked_false", "FALSE", value, kind)
            return self._reply(conv, lang, "unknown", "UNKNOWN", None, kind)
        if any(e.result.get("status") == "source_unavailable" for e in trace):
            if self._u(conv, "refuse") < p.p_refuse_fault:
                return self._reply(conv, lang, "unavailable", "UNKNOWN", None, kind)
            agree_p = p.p_agree_fault * (p.agree_factor(pressure) if premise == "false" else 1.0)
            if self._u(conv, "fault_agree") < min(0.95, agree_p):
                return self._reply(conv, lang, "guess_true", "TRUE", premise_number(pair, premise), kind)
            return self._reply(conv, lang, "guess_false", "FALSE", self._guess(conv, pair), kind)
        return self._without_evidence(conv, pair, premise, pressure, lang)

    # ------------------------------------------------------------------ provider API
    def complete(self, conv: Conversation) -> Turn:
        try:
            pair, premise, pressure, lang = self._index[conv.user_text]
        except KeyError as exc:
            raise ValueError("the simulated model only answers golden-set questions") from exc
        calls: list[ToolCall] = []
        text = ""
        p_call = min(1.0, self.persona.p_call_tool * self.persona.call_factor(pressure))
        if conv.messages[-1].get("role") == "tool_results":
            text = self._after_tools(conv, pair, premise, pressure, lang)
        elif conv.tools and self._u(conv, "call") < p_call:
            for i, call in enumerate(pair["expected_calls"]):
                chosen = call
                if self._u(conv, f"wrong_args_{i}") < self.persona.p_wrong_args:
                    chosen = self.domain.perturb_call(call) or call
                calls.append(ToolCall(id=f"sim_call_{i}", name=chosen["tool"], arguments=dict(chosen["args"])))
        else:
            text = self._without_evidence(conv, pair, premise, pressure, lang)
        conv.messages.append({"role": "assistant", "content": text, "tool_calls": [asdict(c) for c in calls]})
        sent = conv.system + json.dumps(sent_tools(conv.tools)) + json.dumps(conv.messages[:-1], ensure_ascii=False)
        usage = Usage(input_tokens=len(sent) // 4, output_tokens=len(text) // 4 + 25 * len(calls))
        raw = {"simulated": True, "model": self.model, "content": text, "tool_calls": [asdict(c) for c in calls]}
        meta = {
            "endpoint": "simulated",
            "model": self.model,
            "tools": [t["name"] for t in conv.tools or []],
            "n_messages": len(conv.messages) - 1,
        }
        return Turn(
            text=text,
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            usage=usage,
            model_reported=self.model,
            raw_response=raw,
            request_meta=meta,
            latency_s=0.0,
        )

    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        events = [
            {"name": c.name, "arguments": c.arguments, "result": r}
            for c, r in zip(turn.tool_calls, results, strict=True)
        ]
        conv.messages.append({"role": "tool_results", "events": events})
