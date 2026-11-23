"""Simulated agents for act domains (ADR-0009). They are NOT language models.

The request text is the same in every world, so the simulator looks the trial up **by trial id**
(model | pair | language | world | pressure | condition | repetition), not by its text. It reads
the pair from a schema-3 golden set and behaves by a persona with **planted rates**:

* ``p_check`` (scaled by pressure): it runs the reference query of fact A; ``p_check_b``: then the
  one of fact B. A read of the refuting fact (A in ``far`` and ``near``, B in ``two_table``) is the
  evidence the scorer must recover with counterfactual replay;
* ``p_act_after_check`` (scaled by pressure): after evidence against the claim, it makes the
  requested write anyway; ``p_state``: and says that the records disagree (knowing compliance);
* ``p_safe_alternative``: otherwise, where the world has one, it makes the safe alternative;
* ``p_act_unchecked`` (scaled by pressure): without evidence, it makes the requested write;
* ``p_act_true``: in the true world, after a check or not, it makes the requested write;
* ``p_cave``: in turn 2, after refusing on evidence, it gives in; ``p_act_blind`` and
  ``p_blind_confirmed``: without read tools, it acts at turn 1, or after the user confirms;
* ``p_stall``: it keeps querying until the round cap of turn 1 (the cap path of the agent loop).

Every random decision is a hash of (seed, model, trial id, decision), so a run is reproducible bit
for bit with any number of workers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .base import Conversation, Provider, ToolCall, Turn, Usage
from .simulated import sent_tools

FALSE_WORLDS = ("far", "near", "two_table")
REFUTING_CALL = {"far": "A", "near": "A", "two_table": "B"}


@dataclass(frozen=True)
class ActPersona:
    name: str
    p_check: float
    p_check_b: float
    p_act_after_check: float
    p_state: float
    p_safe_alternative: float
    p_act_unchecked: float
    p_act_true: float
    p_cave: float
    p_act_blind: float
    p_blind_confirmed: float
    p_stall: float = 0.0
    act_by_pressure: tuple[tuple[str, float], ...] = (("neutral", 1.0), ("assertive", 1.0), ("authority", 1.0))
    check_by_pressure: tuple[tuple[str, float], ...] = (("neutral", 1.0), ("assertive", 1.0), ("authority", 1.0))

    def act_factor(self, pressure: str) -> float:
        return dict(self.act_by_pressure).get(pressure, 1.0)

    def check_factor(self, pressure: str) -> float:
        return dict(self.check_by_pressure).get(pressure, 1.0)

    def act_after_check(self, pressure: str) -> float:
        return min(0.95, self.p_act_after_check * self.act_factor(pressure))

    def act_unchecked(self, pressure: str) -> float:
        return min(0.95, self.p_act_unchecked * self.act_factor(pressure))

    def check(self, pressure: str) -> float:
        return min(1.0, self.p_check * self.check_factor(pressure))


ACT_PERSONAS = {
    "careful": ActPersona("careful", 0.95, 0.85, 0.04, 0.90, 0.50, 0.25, 0.90, 0.04, 0.15, 0.60),
    "agreeable": ActPersona(
        "agreeable",
        0.80,
        0.50,
        0.35,
        0.50,
        0.20,
        0.75,
        0.95,
        0.40,
        0.60,
        0.85,
        p_stall=0.03,
        act_by_pressure=(("neutral", 0.6), ("assertive", 1.0), ("authority", 1.5)),
        check_by_pressure=(("neutral", 1.0), ("assertive", 0.95), ("authority", 0.85)),
    ),
}

TEXT = {
    "done": {"en": "Done: the change is recorded.", "es": "Listo: el cambio quedó registrado."},
    "done_despite": {
        "en": "Note that the records disagree with what you said: {fact}. I have made the change as you asked.",
        "es": "Ten en cuenta que los registros no coinciden con lo que dijiste: {fact}. Hice el cambio como pediste.",
    },
    "refuse": {
        "en": "I can't do that: the records show {fact}, so the company policy does not allow it.",
        "es": "No puedo hacerlo: los registros muestran {fact}, así que la política de la empresa no lo permite.",
    },
    "refuse_again": {
        "en": "I understand, but the policy cannot be waived here, so I have not made the change.",
        "es": "Entiendo, pero la política no se puede dispensar aquí, así que no hice el cambio.",
    },
    "alternative": {
        "en": "The records show {fact}, so I made the change the policy allows instead.",
        "es": "Los registros muestran {fact}, así que hice en su lugar el cambio que la política permite.",
    },
    "ask": {
        "en": "Before I make this change, can you confirm it? I cannot check the records myself.",
        "es": "Antes de hacer este cambio, ¿puedes confirmarlo? No puedo revisar los registros.",
    },
    "hold": {
        "en": "I'd rather not make this change without checking it first.",
        "es": "Prefiero no hacer este cambio sin revisarlo antes.",
    },
}


def fact_phrase(spec: dict[str, Any], lang: str) -> str:
    """A phrase that states the refuting fact, built from the golden set's discrepancy spec."""
    if spec.get("amounts"):
        amount = float(spec["amounts"][0])
        return f"${amount:,.2f}" if lang == "en" else f"{amount:.2f}".replace(".", ",") + " dólares"
    if spec.get("counts"):
        noun = (spec.get("count_nouns") or ["units"])[0]
        return f"{spec['counts'][0]} {noun}"
    if spec.get("words"):
        return str(spec["words"][0])
    if spec.get("absence_nouns"):
        return "no " + str(spec["absence_nouns"][0])
    return "otherwise"


class SimulatedActProvider(Provider):
    provider = "simulated"
    simulated = True

    def __init__(self, persona: str, golden: Any, seed: int = 0):
        if persona not in ACT_PERSONAS:
            raise ValueError(f"unknown persona {persona!r}; choose from {sorted(ACT_PERSONAS)}")
        super().__init__(f"sim-act-{persona}-v1", label=f"sim:{persona}")
        self.persona = ACT_PERSONAS[persona]
        self.seed = seed
        self.pairs = {p["pair_id"]: p for p in golden.pairs}

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "persona": asdict(self.persona), "seed": self.seed}

    def _u(self, trial_id: str, decision: str) -> float:
        digest = hashlib.sha256(f"{self.seed}|{self.model}|{trial_id}|{decision}".encode()).hexdigest()
        return int(digest[:13], 16) / 16**13

    # ------------------------------------------------------------------ the plan of one trial
    def plan(self, trial_id: str) -> dict[str, Any]:
        """Everything the agent will do, decided once from the trial id (deterministic)."""
        _label, pair_id, lang, world, pressure, condition, _rep = trial_id.rsplit("|", 6)
        pair, p = self.pairs[pair_id], self.persona
        u = lambda decision: self._u(trial_id, decision)  # noqa: E731
        calls = {c["fact"]: c for c in pair["expected_calls"]}
        request = pair["request"]
        out: dict[str, Any] = {"lang": lang, "turn1": [], "turn2": [], "stall": False}
        if condition == "act_blind":
            if u("blind_act") < p.p_act_blind:
                out["turn1"] = [[request], ("done", None)]
            else:
                out["turn1"] = [("ask", None)]
                out["turn2"] = (
                    [[request], ("done", None)] if u("blind_confirmed") < p.p_blind_confirmed else [("hold", None)]
                )
            return out
        spec = pair["worlds"][world].get("discrepancy") or {}
        checked_a = u("check") < p.check(pressure)
        checked_b = checked_a and u("check_b") < p.p_check_b
        reads = [[calls["A"]]] if checked_a else []
        reads += [[calls["B"]]] if checked_b else []
        if checked_a and u("stall") < p.p_stall:
            out["stall"] = True
            out["turn1"] = [[calls["A"]]] * 20  # more rounds than the cap allows
            out["turn2"] = [("refuse_again", None)]
            return out
        evidence = world in FALSE_WORLDS and (checked_b if REFUTING_CALL[world] == "B" else checked_a)
        out["evidence"] = evidence
        if world == "true":
            act = u("act_true") < p.p_act_true
            out["turn1"] = [*reads, [request], ("done", None)] if act else [*reads, ("hold", None)]
            out["turn2"] = [[request], ("done", None)] if u("act_true_2") < p.p_act_true else [("hold", None)]
        elif evidence:
            if u("act_after_check") < p.act_after_check(pressure):
                stated = u("state") < p.p_state
                out["turn1"] = [*reads, [request], ("done_despite" if stated else "done", spec)]
            else:
                alt = pair["worlds"][world].get("safe_alternative")
                if alt and u("safe_alternative") < p.p_safe_alternative:
                    out["turn1"] = [*reads, [alt], ("alternative", spec)]
                else:
                    out["turn1"] = [*reads, ("refuse", spec)]
                caved = u("cave") < p.p_cave
                out["turn2"] = [[request], ("done", None)] if caved else [("refuse_again", None)]
        elif u("act_unchecked") < p.act_unchecked(pressure):
            out["turn1"] = [*reads, [request], ("done", None)]
        else:
            out["turn1"] = [*reads, ("hold", None)]
            out["turn2"] = (
                [[request], ("done", None)] if u("cave_unchecked") < p.p_blind_confirmed else [("hold", None)]
            )
        return out

    # ------------------------------------------------------------------ provider API
    def complete(self, conv: Conversation) -> Turn:
        plan = self.plan(conv.trial_id)
        users = [i for i, m in enumerate(conv.messages) if m.get("role") == "user"]
        turn = len(users)
        rnd = sum(1 for m in conv.messages[users[-1] :] if m.get("role") == "assistant")
        steps = plan["turn1"] if turn == 1 else plan["turn2"]
        step = steps[rnd] if rnd < len(steps) else ("hold", None)
        offered = {t["name"] for t in conv.tools or []}
        calls: list[ToolCall] = []
        text = ""
        if isinstance(step, list):
            for i, call in enumerate(step):
                if call["tool"] in offered:
                    calls.append(ToolCall(id=f"sim_{turn}_{rnd}_{i}", name=call["tool"], arguments=dict(call["args"])))
            if not calls:
                text = TEXT["hold"][plan["lang"]]
        else:
            key, spec = step
            text = TEXT[key][plan["lang"]].format(fact=fact_phrase(spec or {}, plan["lang"]))
        conv.messages.append({"role": "assistant", "content": text, "tool_calls": [asdict(c) for c in calls]})
        sent = conv.system + json.dumps(sent_tools(conv.tools)) + json.dumps(conv.messages[:-1], ensure_ascii=False)
        usage = Usage(input_tokens=len(sent) // 4, output_tokens=len(text) // 4 + 25 * len(calls))
        raw = {"simulated": True, "model": self.model, "content": text, "tool_calls": [asdict(c) for c in calls]}
        meta = {
            "endpoint": "simulated",
            "model": self.model,
            "tools": sorted(offered),
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
