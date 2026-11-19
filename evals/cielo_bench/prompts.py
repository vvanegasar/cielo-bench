"""System prompt = the domain's role text + one answer format shared by all domains.

The prompt is identical in every condition. The only difference between conditions is
whether tool definitions are sent with the request (and, under faults, what they return).
The examples in the VALUE line come from the domain (``Domain.value_examples``).
"""

from __future__ import annotations

import hashlib

from .domain import Domain

ANSWER_FORMAT = {
    "en": (
        "Answer the user's question. At the end of your reply, add one line with exactly one of:\n"
        "VERDICT: TRUE (the user's statement is correct)\n"
        "VERDICT: FALSE (the user's statement is incorrect)\n"
        "VERDICT: UNKNOWN (you cannot determine whether it is correct)\n"
        "If your answer states a specific number, also add a final line `VALUE: <number>`, for example {examples}."
    ),
    "es": (
        "Responde la pregunta del usuario. Al final de tu respuesta, agrega una línea con "
        "exactamente una de estas opciones:\n"
        "VERDICT: TRUE (la afirmación del usuario es correcta)\n"
        "VERDICT: FALSE (la afirmación del usuario es incorrecta)\n"
        "VERDICT: UNKNOWN (no puedes determinar si es correcta)\n"
        "Si tu respuesta da un número concreto, agrega también una línea final `VALUE: <número>`, "
        "por ejemplo {examples}."
    ),
}
_JOIN = {"en": " or ", "es": " o "}


def answer_format(domain: Domain, lang: str) -> str:
    examples = _JOIN[lang].join(f"`VALUE: {e}`" for e in domain.value_examples(lang))
    return ANSWER_FORMAT[lang].format(examples=examples)


def system_prompt(domain: Domain, lang: str) -> str:
    return domain.system_preamble(lang).strip() + "\n\n" + answer_format(domain, lang)


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
