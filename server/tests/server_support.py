"""Constants and helpers shared by the server tests."""

from __future__ import annotations

from typing import Any

# Cached in evals/fixtures/astronomy/horizons (the same calls the benchmark's own tests use).
SATURN_AT_21 = {"body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"}
SATURN_ON_DAY = {"body": "Saturn", "location": {"city": "Medellín"}, "date": "2026-12-12"}
VENUS_FROM_JUPITER = {"body": "Venus", "location": {"city": "Medellín"}, "datetime": "2026-12-12T05:00:00-05:00",
                      "relative_to": "Jupiter"}
MOON_AT_1930 = {"location": {"city": "Medellín"}, "datetime": "2026-12-26T19:30:00-05:00"}


def numbers_in(result: dict[str, Any]) -> list[Any]:
    """Every numeric value in a flat result (booleans are not values)."""
    return [v for v in result.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
