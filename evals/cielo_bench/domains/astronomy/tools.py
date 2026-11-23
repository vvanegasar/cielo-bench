"""Local tool executors for the astronomy domain (ADR-0005); contracts in docs/TOOLS.md.

* ``body_position``: where a body is at a time and place; optionally its angular separation
  from a second body (``relative_to``), and the rate at which its altitude changes.
* ``body_rise_set``: rise, culmination and set for one local date, with the azimuth at rise
  and set.
* ``moon_phase``: illuminated fraction of the Moon and whether it is waxing or waning.

Every result is a JSON object with ``status``. Successful results carry ``sources[]`` and a
credit line. Failures carry no values at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .ephemeris import DayTable, Ephemeris, PhaseTable, separation_deg
from .horizons import CREDIT, ENDPOINT, SERVICE, SourceUnavailable
from .sky import BODIES, CITIES, UTC, City, hhmm, minutes_of_day, parse_date, parse_datetime, resolve_body, resolve_city

LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "enum": list(CITIES), "description": "A city from the built-in table."},
    },
    "required": ["city"],
    "additionalProperties": False,
}
DATETIME_SCHEMA = {
    "type": "string",
    "description": (
        "Date and time in ISO 8601, for example 2026-12-12T21:00:00-05:00. Without a UTC offset it is read as "
        "local time in the city (Colombia, UTC-5)."
    ),
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "body_position",
        "description": (
            "Position of a solar-system body in the sky at a given date and time, as seen from a city. Data from "
            "NASA/JPL Horizons. Returns the apparent altitude above the horizon in degrees (including atmospheric "
            "refraction; negative means below the horizon), the azimuth in degrees (measured from north through "
            "east), how fast the altitude is changing (degrees per hour; positive means the body is climbing), "
            "right ascension, declination, distance from the observer, and whether the body is above the horizon. "
            "With relative_to, it also returns the angular separation in the sky between the two bodies. If "
            "Horizons cannot be reached, the result has status 'source_unavailable' and contains no values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "body": {"type": "string", "enum": list(BODIES)},
                "location": LOCATION_SCHEMA,
                "datetime": DATETIME_SCHEMA,
                "relative_to": {
                    "type": "string",
                    "enum": list(BODIES),
                    "description": "Optional second body: adds separation_deg, the angle between the two bodies.",
                },
            },
            "required": ["body", "location", "datetime"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},  # read-only: the MCP server serves only such tools
    },
    {
        "name": "body_rise_set",
        "description": (
            "Rise, culmination (highest point in the sky) and set of a solar-system body on one local calendar "
            "date, as seen from a city. Data from NASA/JPL Horizons. Times are given in local time (Colombia, "
            "UTC-5) and in UTC; rise and set also give the azimuth where the body crosses the horizon, and the "
            "culmination gives the maximum altitude. Rise and set are when the apparent (refracted) altitude of "
            "the body's centre crosses 0 degrees. An event that does not happen on that date is null. If Horizons "
            "cannot be reached, the result has status 'source_unavailable' and contains no values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "body": {"type": "string", "enum": list(BODIES)},
                "location": LOCATION_SCHEMA,
                "date": {"type": "string", "description": "Local calendar date, YYYY-MM-DD."},
            },
            "required": ["body", "location", "date"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},  # read-only: the MCP server serves only such tools
    },
    {
        "name": "moon_phase",
        "description": (
            "Phase of the Moon at a given date and time, as seen from a city. Data from NASA/JPL Horizons. Returns "
            "the illuminated fraction of the Moon's disk in percent, whether the Moon is waxing or waning, and the "
            "angle between the Sun and the Moon. If Horizons cannot be reached, the result has status "
            "'source_unavailable' and contains no values."
        ),
        "parameters": {
            "type": "object",
            "properties": {"location": LOCATION_SCHEMA, "datetime": DATETIME_SCHEMA},
            "required": ["location", "datetime"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},  # read-only: the MCP server serves only such tools
    },
]

RISE_SET_DEFINITION = (
    "Rise and set: the apparent (refracted) altitude of the body's centre crosses 0 degrees. "
    "Culmination: maximum apparent altitude. Computed from 1-minute NASA/JPL Horizons samples."
)
_KEEP = ("COMMAND", "CENTER", "SITE_COORD", "START_TIME", "STOP_TIME", "STEP_SIZE", "QUANTITIES", "APPARENT")


def _iso_utc(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_local(t: datetime, city: City) -> str:
    return t.astimezone(city.tz).isoformat(timespec="seconds")


def _location(city: City) -> dict[str, Any]:
    return {"city": city.name, "lat": city.lat, "lon": city.lon, "elevation_m": city.elevation_m}


def _sources(*tables: DayTable | PhaseTable) -> list[dict[str, Any]]:
    out = []
    for table in tables:
        q = table.source.query
        out.append(
            {
                "service": SERVICE,
                "endpoint": ENDPOINT,
                "query": {k: q[k] for k in _KEEP if k in q},
                "retrieved_at_utc": table.source.retrieved_at_utc,
                "response_sha256": table.source.sha256,
            }
        )
    return out


def _invalid(message: str) -> dict[str, Any]:
    return {"status": "invalid_input", "message": message}


def unavailable(exc: SourceUnavailable) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "source": exc.source,
        "reason": exc.reason,
        "message": f"{exc.source} could not provide data ({exc.reason}). No values are returned.",
    }


def _event(t: datetime | None, city: City, azimuth: float | None = None) -> dict[str, Any] | None:
    if t is None:
        return None
    out: dict[str, Any] = {
        "local": _iso_local(t, city),
        "local_time": hhmm(minutes_of_day(t, city.tz)),
        "utc": _iso_utc(t),
    }
    if azimuth is not None:
        out["azimuth_deg"] = round(azimuth, 2)
    return out


def _city(arguments: dict[str, Any]) -> City | None:
    location = arguments.get("location")
    return resolve_city(location.get("city")) if isinstance(location, dict) else None


class AstronomyToolExecutor:
    def __init__(self, ephemeris: Ephemeris):
        self.ephemeris = ephemeris

    @property
    def live_requests(self) -> int:
        return self.ephemeris.client.live_requests

    def execute(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return _invalid("arguments must be a JSON object")
        if name == "body_position":
            return self._body_position(arguments)
        if name == "body_rise_set":
            return self._body_rise_set(arguments)
        if name == "moon_phase":
            return self._moon_phase(arguments)
        return {"status": "out_of_scope", "message": f"unknown tool {name!r}"}

    @staticmethod
    def _common(arguments: dict[str, Any]) -> tuple[str | None, City | None, str | None]:
        body = resolve_body(arguments.get("body"))
        if body is None:
            return None, None, f"body must be one of {list(BODIES)}"
        city = _city(arguments)
        if city is None:
            return None, None, f"location.city must be one of {list(CITIES)}"
        return body, city, None

    def _body_position(self, arguments: dict[str, Any]) -> dict[str, Any]:
        body, city, error = self._common(arguments)
        if error:
            return _invalid(error)
        assert body is not None and city is not None
        instant = parse_datetime(arguments.get("datetime"), city.tz)
        if instant is None:
            return _invalid("datetime must be ISO 8601, for example 2026-12-12T21:00:00-05:00")
        other = None
        if arguments.get("relative_to") not in (None, ""):
            other = resolve_body(arguments.get("relative_to"))
            if other is None or other == body:
                return _invalid(f"relative_to must be another body, one of {list(BODIES)}")
        try:
            pos, table = self.ephemeris.position(body, city, instant)
            rate = table.altitude_rate(instant)
            other_pos, other_table = self.ephemeris.position(other, city, instant) if other else (None, None)
        except SourceUnavailable as exc:
            return unavailable(exc)
        result: dict[str, Any] = {
            "status": "ok",
            "body": body,
            "location": _location(city),
            "datetime_utc": _iso_utc(instant),
            "datetime_local": _iso_local(instant, city),
            "altitude_deg": round(pos.altitude_deg, 2),
            "azimuth_deg": round(pos.azimuth_deg, 2),
            "altitude_rate_deg_per_hour": round(rate, 2),
            "ra_hours": round(pos.ra_deg / 15.0, 4),
            "dec_deg": round(pos.dec_deg, 3),
            "distance_au": round(pos.distance_au, 6),
            "above_horizon": pos.altitude_deg > 0.0,
            "interpolated": pos.interpolated,
            "notes": "Apparent altitude includes atmospheric refraction. Azimuth: degrees from north through east.",
        }
        tables: list[DayTable] = [table]
        if other_pos is not None and other_table is not None:
            result["relative_to"] = other
            result["separation_deg"] = round(
                separation_deg(pos.ra_deg, pos.dec_deg, other_pos.ra_deg, other_pos.dec_deg), 2
            )
            tables.append(other_table)
        result["sources"] = _sources(*tables)
        result["credit"] = CREDIT
        return result

    def _body_rise_set(self, arguments: dict[str, Any]) -> dict[str, Any]:
        body, city, error = self._common(arguments)
        if error:
            return _invalid(error)
        assert body is not None and city is not None
        local_date = parse_date(arguments.get("date"))
        if local_date is None:
            return _invalid("date must be YYYY-MM-DD")
        try:
            events, table = self.ephemeris.events(body, city, local_date)
        except SourceUnavailable as exc:
            return unavailable(exc)
        culmination = _event(events.culmination, city)
        if culmination is not None and events.culmination_altitude_deg is not None:
            culmination["altitude_deg"] = round(events.culmination_altitude_deg, 2)
        return {
            "status": "ok",
            "body": body,
            "location": _location(city),
            "date_local": local_date.isoformat(),
            "rise": _event(events.rise, city, events.rise_azimuth_deg),
            "culmination": culmination,
            "set": _event(events.set, city, events.set_azimuth_deg),
            "definition": RISE_SET_DEFINITION,
            "sources": _sources(table),
            "credit": CREDIT,
        }

    def _moon_phase(self, arguments: dict[str, Any]) -> dict[str, Any]:
        city = _city(arguments)
        if city is None:
            return _invalid(f"location.city must be one of {list(CITIES)}")
        instant = parse_datetime(arguments.get("datetime"), city.tz)
        if instant is None:
            return _invalid("datetime must be ISO 8601, for example 2026-12-12T21:00:00-05:00")
        try:
            (illuminated, elongation, waxing), table = self.ephemeris.moon_phase(city, instant)
        except SourceUnavailable as exc:
            return unavailable(exc)
        return {
            "status": "ok",
            "body": "Moon",
            "location": _location(city),
            "datetime_utc": _iso_utc(instant),
            "datetime_local": _iso_local(instant, city),
            "illuminated_fraction_pct": round(illuminated, 2),
            "phase": "waxing" if waxing else "waning",
            "sun_moon_elongation_deg": round(elongation, 2),
            "notes": "Illuminated fraction of the disk as seen from the city (Horizons quantity 10), interpolated "
            "between hourly samples. Waxing: the Moon trails the Sun (Horizons flag /T).",
            "sources": _sources(table),
            "credit": CREDIT,
        }
