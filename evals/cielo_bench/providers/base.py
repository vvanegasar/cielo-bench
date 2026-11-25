"""Provider interface: one conversation with one model, with optional tool calling."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None
    raw_arguments: str | None = None
    parse_error: str | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: Usage) -> None:
        for name in asdict(self):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str | None
    usage: Usage
    model_reported: str | None
    raw_response: dict[str, Any]
    request_meta: dict[str, Any]
    latency_s: float


@dataclass
class Conversation:
    system: str
    user_text: str
    tools: list[dict[str, Any]] | None
    trial_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class Provider(ABC):
    provider: str = ""
    simulated: bool = False

    def __init__(self, model: str, label: str | None = None):
        self.model = model
        self.label = label or f"{self.provider}:{model}"

    def describe(self) -> dict[str, Any]:
        """Settings recorded in the run manifest. Never includes secrets."""
        return {"label": self.label, "provider": self.provider, "model": self.model, "simulated": self.simulated}

    @staticmethod
    def salt(conv: Conversation) -> str:
        """Output-cache salt: the trial id and the round number within the conversation."""
        rounds = sum(1 for m in conv.messages if m.get("role") == "assistant")
        return f"{conv.trial_id}|round{rounds}"

    def new_conversation(
        self, system: str, user_text: str, tools: list[dict[str, Any]] | None, trial_id: str
    ) -> Conversation:
        conv = Conversation(system=system, user_text=user_text, tools=tools, trial_id=trial_id)
        conv.messages.append({"role": "user", "content": user_text})
        return conv

    @abstractmethod
    def complete(self, conv: Conversation) -> Turn:
        """Send the conversation, append the assistant message to it, return the turn."""

    def add_user_message(self, conv: Conversation, text: str) -> None:
        """Append a follow-up user turn after the assistant's final answer (multi-turn designs)."""
        conv.messages.append({"role": "user", "content": text})

    @abstractmethod
    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        """Append the results of ``turn.tool_calls`` (same order) to the conversation."""
