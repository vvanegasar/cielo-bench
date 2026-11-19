"""Built-in locations, bodies, names and time helpers for the astronomy domain."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo

UTC = UTC
COT = timezone(timedelta(hours=-5), "COT")  # Colombia: UTC-5 all year (no daylight saving)


@dataclass(frozen=True)
class City:
    name: str
    lat: float  # degrees, north positive
    lon: float  # degrees, east positive
    elevation_m: float
    tz: tzinfo = COT


# Approximate city-centre coordinates. Ground truth is computed for exactly these values,
# and the tool answers for exactly these values, so both sides agree by construction.
CITIES: dict[str, City] = {
    "Medellín": City("Medellín", 6.2447, -75.5748, 1495.0),
    "Bogotá": City("Bogotá", 4.7110, -74.0721, 2640.0),
    "Barranquilla": City("Barranquilla", 10.9639, -74.7964, 18.0),
}

# NASA/JPL Horizons target IDs (body centres).
BODIES: dict[str, str] = {
    "Sun": "10",
    "Moon": "301",
    "Mercury": "199",
    "Venus": "299",
    "Mars": "499",
    "Jupiter": "599",
    "Saturn": "699",
    "Uranus": "799",
    "Neptune": "899",
}

BODY_EN = {"Sun": "the Sun", "Moon": "the Moon"}  # others: the plain name
BODY_ES = {
    "Sun": "el Sol",
    "Moon": "la Luna",
    "Mercury": "Mercurio",
    "Venus": "Venus",
    "Mars": "Marte",
    "Jupiter": "Júpiter",
    "Saturn": "Saturno",
    "Uranus": "Urano",
    "Neptune": "Neptuno",
}
# Spanish direct object ("para ver a Saturno", "para ver la Luna").
BODY_ES_OBJECT = {"Sun": "el Sol", "Moon": "la Luna"}

CARDINAL_CENTER = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}
CARDINAL_ES = {"north": "norte", "east": "este", "south": "sur", "west": "oeste"}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}

WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace(",", " ").split())


_BODY_ALIASES: dict[str, str] = {}
for _key in BODIES:
    _BODY_ALIASES[normalize_name(_key)] = _key
    _BODY_ALIASES[normalize_name(BODY_ES[_key])] = _key
    _BODY_ALIASES[normalize_name(BODY_ES[_key].split()[-1])] = _key


def resolve_body(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _BODY_ALIASES.get(normalize_name(value))


def resolve_city(value: object) -> City | None:
    if not isinstance(value, str):
        return None
    wanted = normalize_name(value)
    for name, city in CITIES.items():
        base = normalize_name(name)
        if wanted in (base, f"{base} colombia"):
            return city
    return None


def parse_datetime(value: object, tz: tzinfo) -> datetime | None:
    """Parse ISO 8601. A value without a UTC offset is read in the given time zone."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed


def parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def cardinal_4(azimuth_deg: float) -> str:
    a = azimuth_deg % 360.0
    if a >= 315.0 or a < 45.0:
        return "north"
    if a < 135.0:
        return "east"
    if a < 225.0:
        return "south"
    return "west"


def angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def minutes_of_day(dt: datetime, tz: tzinfo) -> float:
    local = dt.astimezone(tz)
    return local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 6e7


def hhmm(minutes: float) -> str:
    total = round(minutes) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def format_date(d: date, lang: str) -> str:
    if lang == "es":
        return f"{WEEKDAYS_ES[d.weekday()]} {d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"
    return f"{WEEKDAYS_EN[d.weekday()]}, {d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def body_name(body: str, lang: str, *, as_object: bool = False) -> str:
    if lang == "es":
        if as_object:
            return BODY_ES_OBJECT.get(body, f"a {BODY_ES[body]}")
        return BODY_ES[body]
    return BODY_EN.get(body, body)
