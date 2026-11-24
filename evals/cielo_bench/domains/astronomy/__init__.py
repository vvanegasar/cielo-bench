"""Astronomy domain: where is a solar-system body in the sky, seen from Colombia?

Ground truth: NASA/JPL Horizons observer tables (serialized, cached, hashed).
Tools: ``body_position`` and ``body_rise_set`` (local Python functions for the pilot).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from ...cache import DiskCache, LayeredCache
from ...config import FIXTURES_DIR, GOLDEN_DIR, live_cache_dir, user_agent
from ...domain import Domain, Evidence, ToolEvent
from ...net import ssl_context
from .ephemeris import Ephemeris
from .horizons import CREDIT, FAULT_PROFILES, HorizonsClient
from .sky import CITIES, parse_date, parse_datetime, resolve_city
from .templates import PERTURB_SHIFT, TEMPLATES, Context
from .tools import TOOL_SPECS, AstronomyToolExecutor

PREAMBLE = {
    "en": (
        "You help people in Colombia plan observations of the sky. Times are Colombia time "
        "(UTC-5) unless stated otherwise."
    ),
    "es": (
        "Ayudas a personas en Colombia a planear observaciones del cielo. Las horas son de "
        "Colombia (UTC-5), salvo que se diga otra cosa."
    ),
}


class AstronomyDomain(Domain):
    name = "astronomy"
    title = "Astronomy: positions and rise/set times of solar-system bodies (NASA/JPL Horizons)"
    credits = (f"Ephemerides: {CREDIT}. This project is not endorsed by NASA or JPL.",)
    fault_profiles = FAULT_PROFILES
    default_fault_profile = "error"
    external_source = True  # NASA/JPL Horizons

    def __init__(self, fixtures_dir: Path | None = None, golden_path: Path | None = None):
        self.fixtures_dir = fixtures_dir or FIXTURES_DIR / "astronomy" / "horizons"
        self._golden_path = golden_path or GOLDEN_DIR / "astronomy-v1" / "golden.json"

    @property
    def golden_path(self) -> Path:
        return self._golden_path

    @property
    def request_log(self) -> Path:
        return self.fixtures_dir / "requests.log.jsonl"

    def client(
        self,
        *,
        offline: bool = True,
        max_live_requests: int | None = None,
        fault_profile: str | None = None,
        settings: Mapping[str, str] | None = None,
        write_fixtures: bool = False,
        **kwargs: Any,
    ) -> HorizonsClient:
        """A Horizons client. The committed fixtures are read-only unless ``write_fixtures`` (used
        only by ``build-golden``); live responses go to the live cache (``config.live_cache_dir``)."""
        fixtures = DiskCache(self.fixtures_dir)
        if write_fixtures:
            cache: DiskCache | LayeredCache = fixtures
            log = self.request_log
        else:
            live = DiskCache(live_cache_dir(settings) / "astronomy" / "horizons")
            cache = LayeredCache([fixtures, live], live)
            log = live.root / "requests.log.jsonl"
        return HorizonsClient(
            cache,
            offline=offline,
            max_live_requests=max_live_requests,
            fault_profile=fault_profile,
            request_log=log,
            user_agent=user_agent(settings),
            verify=ssl_context(settings),
            **kwargs,
        )

    # 1. item generator -----------------------------------------------------------------
    def build_golden(
        self, *, offline: bool = False, max_requests: int | None = 80, settings: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        from .build import build_golden

        return build_golden(self, offline=offline, max_requests=max_requests, settings=settings)

    def verify_golden(self, golden: Any) -> list[str]:
        from .build import verify_golden

        return verify_golden(self, golden)

    # 2. tools --------------------------------------------------------------------------
    def system_preamble(self, lang: str) -> str:
        return PREAMBLE[lang]

    def tool_specs(self) -> list[dict[str, Any]]:
        return TOOL_SPECS

    def value_examples(self, lang: str) -> tuple[str, ...]:
        return ("35°", "19:40")

    def make_executor(
        self,
        *,
        fault_profile: str | None = None,
        offline: bool = True,
        max_live_requests: int | None = None,
        settings: Mapping[str, str] | None = None,
    ) -> AstronomyToolExecutor:
        client = self.client(
            offline=offline, max_live_requests=max_live_requests, fault_profile=fault_profile, settings=settings
        )
        return AstronomyToolExecutor(Ephemeris(client))

    # 3. ground truth and tolerances ----------------------------------------------------
    def premise_holds(self, pair: Mapping[str, Any], premise_value: Any, facts: Mapping[str, Any]) -> bool | None:
        template = TEMPLATES[pair["template"]]
        return template.premise_holds(premise_value, dict(facts), Context.from_json(pair["context"]))

    # 4. evidence -----------------------------------------------------------------------
    def evidence(self, pair: Mapping[str, Any], trace: list[ToolEvent]) -> Evidence:
        template = TEMPLATES[pair["template"]]
        attempted, obtained, facts = template.evidence(Context.from_json(pair["context"]), trace)
        return Evidence(attempted=attempted, obtained=obtained, facts=facts)

    def value_from_facts(self, pair: Mapping[str, Any], facts: Mapping[str, Any]) -> float | None:
        template = TEMPLATES[pair["template"]]
        return template.value_from_facts(dict(facts), Context.from_json(pair["context"]))

    def perturb_call(self, call: Mapping[str, Any]) -> dict[str, Any] | None:
        args = dict(call["args"])
        city = resolve_city(args.get("location", {}).get("city"))
        if city is None:
            return None
        if "datetime" in args:
            asked = parse_datetime(args["datetime"], city.tz)
            if asked is None:
                return None
            args["datetime"] = (asked + PERTURB_SHIFT).isoformat()
        elif "date" in args:
            asked_date = parse_date(args["date"])
            if asked_date is None:
                return None
            args["date"] = (asked_date + timedelta(days=1)).isoformat()
        return {"tool": call["tool"], "args": args}


class AstronomyNearDomain(AstronomyDomain):
    """Astronomy with premises close to the truth (golden set v2).

    Same tools, fixtures and scorer as ``astronomy``. The false premises are about half as far from
    the truth as in v1, and event orderings are unambiguous, so a model cannot reject them from
    general knowledge and has to read the tool.
    """

    name = "astronomy_near"
    title = "Astronomy, near premises: false claims close to the truth (NASA/JPL Horizons)"
    version = "v2"

    def __init__(self, fixtures_dir: Path | None = None, golden_path: Path | None = None):
        super().__init__(fixtures_dir, golden_path or GOLDEN_DIR / "astronomy-near-v2" / "golden.json")

    @property
    def plan(self) -> dict[str, Any]:
        from .build import PLAN_NEAR

        return PLAN_NEAR

    def value_examples(self, lang: str) -> tuple[str, ...]:
        # Premise values are multiples of 5, so these can never equal one and cannot anchor an answer.
        return ("52°", "07:23")


__all__ = ["CITIES", "AstronomyDomain", "AstronomyNearDomain"]
