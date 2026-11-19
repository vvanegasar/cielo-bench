"""Parse Horizons observer tables and answer position and rise/set questions from them.

Definitions used everywhere (tool answers and ground truth alike):

* altitude and azimuth: Horizons apparent values with atmospheric refraction
  (``APPARENT='REFRACTED'``, columns ``Elev_(r-app)`` and ``Azi_(r-app)``); azimuth is
  measured from north through east;
* rise and set: the instant the refracted apparent altitude of the body's centre crosses
  0°, interpolated linearly between the two 1-minute samples that bracket it;
* culmination: the time of maximum refracted altitude (parabolic fit around the highest
  sample).

Horizons' own rise/transit/set markers (true visual horizon, which includes the horizon
dip for the site's height) are kept alongside as a cross-check; they are not the truth.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ...cache import CachedResponse
from .horizons import PHASE_WINDOW, HorizonsClient, SourceUnavailable, day_table_query, moon_phase_query
from .sky import UTC, City

MONTHS = {
    m: i
    for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)
}
REQUIRED_COLUMNS = {
    "ra": "R.A._(ICRF)",
    "dec": "DEC_(ICRF)",
    "az": "Azi_(r-app)",
    "el": "Elev_(r-app)",
    "delta": "delta",
}
ROWS_PER_DAY = 1441


class HorizonsFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Sample:
    t: datetime  # UTC
    solar: str
    marker: str
    ra_deg: float
    dec_deg: float
    az_deg: float
    el_deg: float
    delta_au: float


@dataclass(frozen=True)
class Position:
    t: datetime
    altitude_deg: float
    azimuth_deg: float
    ra_deg: float
    dec_deg: float
    distance_au: float
    interpolated: bool


@dataclass(frozen=True)
class Events:
    rise: datetime | None
    set: datetime | None
    culmination: datetime | None
    culmination_altitude_deg: float | None
    n_rises: int
    n_sets: int
    jpl_markers: dict[str, list[str]] = field(default_factory=dict)
    rise_azimuth_deg: float | None = None
    set_azimuth_deg: float | None = None


def _parse_time(text: str) -> datetime:
    try:
        day_part, clock = text.split()
        year, mon, day = day_part.split("-")
        hour, minute = clock.split(":")
        return datetime(int(year), MONTHS[mon], int(day), int(hour), int(minute), tzinfo=UTC)
    except (ValueError, KeyError) as exc:
        raise HorizonsFormatError(f"bad time stamp {text!r}") from exc


def _number(text: str, column: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise HorizonsFormatError(f"non-numeric value {text!r} in column {column}") from exc


def parse_observer_table(result_text: str) -> list[Sample]:
    """Parse the CSV observer table between $$SOE and $$EOE."""
    lines = result_text.splitlines()
    try:
        soe = lines.index("$$SOE")
        eoe = lines.index("$$EOE")
    except ValueError as exc:
        raise HorizonsFormatError("missing $$SOE/$$EOE markers") from exc
    header = next((ln for ln in reversed(lines[:soe]) if "Date__(UT)__HR:MN" in ln), None)
    if header is None:
        raise HorizonsFormatError("missing column header")
    columns = [c.strip() for c in header.split(",")]
    index = {name: i for i, name in enumerate(columns) if name}
    missing = [col for col in REQUIRED_COLUMNS.values() if col not in index]
    if missing:
        raise HorizonsFormatError(f"missing columns {missing}")
    samples: list[Sample] = []
    for line in lines[soe + 1 : eoe]:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(columns) - 1:
            raise HorizonsFormatError(f"short row {line!r}")
        samples.append(
            Sample(
                t=_parse_time(parts[0]),
                solar=parts[1],
                marker=parts[2],
                ra_deg=_number(parts[index[REQUIRED_COLUMNS["ra"]]], "ra"),
                dec_deg=_number(parts[index[REQUIRED_COLUMNS["dec"]]], "dec"),
                az_deg=_number(parts[index[REQUIRED_COLUMNS["az"]]], "az"),
                el_deg=_number(parts[index[REQUIRED_COLUMNS["el"]]], "el"),
                delta_au=_number(parts[index[REQUIRED_COLUMNS["delta"]]], "delta"),
            )
        )
    if not samples:
        raise HorizonsFormatError("empty table")
    return samples


def _interp_angle(a0: float, a1: float, f: float) -> float:
    return (a0 + f * (((a1 - a0 + 180.0) % 360.0) - 180.0)) % 360.0


def _lerp(a: float, b: float, f: float) -> float:
    return a + f * (b - a)


@dataclass
class DayTable:
    body: str
    city: City
    local_date: date
    samples: list[Sample]
    source: CachedResponse

    def __post_init__(self) -> None:
        self._index = {s.t: i for i, s in enumerate(self.samples)}

    @property
    def start(self) -> datetime:
        return self.samples[0].t

    @property
    def end(self) -> datetime:
        return self.samples[-1].t

    def position(self, instant: datetime) -> Position:
        t = instant.astimezone(UTC)
        if not self.start <= t <= self.end:
            raise ValueError(f"{t} is outside this table ({self.start} to {self.end})")
        exact = self._index.get(t.replace(second=0, microsecond=0)) if t.second == 0 and t.microsecond == 0 else None
        if exact is not None:
            s = self.samples[exact]
            return Position(s.t, s.el_deg, s.az_deg, s.ra_deg, s.dec_deg, s.delta_au, False)
        i = int((t - self.start).total_seconds() // 60)
        s0, s1 = self.samples[i], self.samples[min(i + 1, len(self.samples) - 1)]
        span = (s1.t - s0.t).total_seconds() or 60.0
        f = (t - s0.t).total_seconds() / span
        return Position(
            t=t,
            altitude_deg=_lerp(s0.el_deg, s1.el_deg, f),
            azimuth_deg=_interp_angle(s0.az_deg, s1.az_deg, f),
            ra_deg=_interp_angle(s0.ra_deg, s1.ra_deg, f),
            dec_deg=_lerp(s0.dec_deg, s1.dec_deg, f),
            distance_au=_lerp(s0.delta_au, s1.delta_au, f),
            interpolated=True,
        )

    def events(self) -> Events:
        rises: list[tuple[datetime, float]] = []
        sets: list[tuple[datetime, float]] = []
        for s0, s1 in zip(self.samples, self.samples[1:], strict=False):
            if s0.el_deg < 0.0 <= s1.el_deg or s0.el_deg >= 0.0 > s1.el_deg:
                f = (0.0 - s0.el_deg) / (s1.el_deg - s0.el_deg)
                crossing = s0.t + (s1.t - s0.t) * f
                azimuth = _interp_angle(s0.az_deg, s1.az_deg, f)
                (rises if s1.el_deg >= 0.0 else sets).append((crossing, azimuth))
        culmination, culmination_alt = None, None
        k = max(range(len(self.samples)), key=lambda j: self.samples[j].el_deg)
        if 0 < k < len(self.samples) - 1:
            y0, y1, y2 = (self.samples[j].el_deg for j in (k - 1, k, k + 1))
            denom = y0 - 2 * y1 + y2
            offset = 0.5 * (y0 - y2) / denom if denom else 0.0
            offset = max(-1.0, min(1.0, offset))
            culmination = self.samples[k].t + timedelta(minutes=offset)
            culmination_alt = y1 - 0.25 * (y0 - y2) * offset
        markers: dict[str, list[str]] = {}
        for s in self.samples:
            if s.marker in ("r", "s", "t", "e"):
                markers.setdefault(s.marker, []).append(_iso(s.t))
        return Events(
            rise=rises[0][0] if rises else None,
            set=sets[0][0] if sets else None,
            culmination=culmination,
            culmination_altitude_deg=culmination_alt,
            n_rises=len(rises),
            n_sets=len(sets),
            jpl_markers=markers,
            rise_azimuth_deg=rises[0][1] if rises else None,
            set_azimuth_deg=sets[0][1] if sets else None,
        )

    def altitude_rate(self, instant: datetime) -> float:
        """Rate of change of the refracted altitude at ``instant``, degrees per hour (central difference)."""
        t = instant.astimezone(UTC)
        before = max(self.start, t - timedelta(minutes=1))
        after = min(self.end, t + timedelta(minutes=1))
        span_h = (after - before).total_seconds() / 3600
        return (self.position(after).altitude_deg - self.position(before).altitude_deg) / span_h


def separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle angle between two directions given in degrees (haversine formula)."""
    r1, d1, r2, d2 = (math.radians(x) for x in (ra1, dec1, ra2, dec2))
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


@dataclass(frozen=True)
class PhaseSample:
    t: datetime
    illuminated_pct: float
    elongation_deg: float
    trailing: bool  # Horizons "/T": the Moon trails the Sun (east of it), i.e. waxing


def parse_phase_table(result_text: str) -> list[PhaseSample]:
    lines = result_text.splitlines()
    try:
        soe, eoe = lines.index("$$SOE"), lines.index("$$EOE")
    except ValueError as exc:
        raise HorizonsFormatError("missing $$SOE/$$EOE markers") from exc
    header = next((ln for ln in reversed(lines[:soe]) if "Date__(UT)__HR:MN" in ln), None)
    if header is None:
        raise HorizonsFormatError("missing column header")
    columns = [c.strip() for c in header.split(",")]
    try:
        i_illum, i_elong, i_flag = columns.index("Illu%"), columns.index("S-O-T"), columns.index("/r")
    except ValueError as exc:
        raise HorizonsFormatError("missing Illu%, S-O-T or /r column") from exc
    out = []
    for line in lines[soe + 1 : eoe]:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        flag = parts[i_flag]
        if flag not in ("/T", "/L"):
            raise HorizonsFormatError(f"unexpected /r flag {flag!r}")
        out.append(
            PhaseSample(
                _parse_time(parts[0]), _number(parts[i_illum], "Illu%"), _number(parts[i_elong], "S-O-T"), flag == "/T"
            )
        )
    if len(out) < 2:
        raise HorizonsFormatError("phase table has fewer than two rows")
    return out


@dataclass
class PhaseTable:
    city: City
    samples: list[PhaseSample]
    source: CachedResponse

    def covers(self, instant: datetime) -> bool:
        return self.samples[0].t <= instant.astimezone(UTC) <= self.samples[-1].t

    def at(self, instant: datetime) -> tuple[float, float, bool]:
        """Illuminated percent, Sun-Moon elongation (deg) and waxing flag at ``instant``."""
        t = instant.astimezone(UTC)
        if not self.covers(t):
            raise ValueError(f"{t} is outside this phase table")
        step = (self.samples[1].t - self.samples[0].t).total_seconds()
        i = min(int((t - self.samples[0].t).total_seconds() // step), len(self.samples) - 2)
        s0, s1 = self.samples[i], self.samples[i + 1]
        f = (t - s0.t).total_seconds() / step
        nearest = s0 if f < 0.5 else s1
        return (
            _lerp(s0.illuminated_pct, s1.illuminated_pct, f),
            _lerp(s0.elongation_deg, s1.elongation_deg, f),
            nearest.trailing,
        )


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class Ephemeris:
    """Day tables on demand (serialized and cached by the client), memoized per instance."""

    def __init__(self, client: HorizonsClient):
        self.client = client
        self._tables: dict[tuple[str, str, date], DayTable] = {}
        self._phase: dict[tuple[str, str, tuple[str, str]], PhaseTable] = {}
        self._lock = threading.Lock()

    def day_table(self, body: str, city: City, local_date: date) -> DayTable:
        key = (body, city.name, local_date)
        with self._lock:
            if key in self._tables:
                return self._tables[key]
        response = self.client.fetch(day_table_query(body, city, local_date))
        try:
            samples = parse_observer_table(json.loads(response.text)["result"])
        except (HorizonsFormatError, KeyError, ValueError) as exc:
            raise SourceUnavailable("malformed_response", str(exc)) from exc
        start = datetime.combine(local_date, time(0, 0), tzinfo=city.tz).astimezone(UTC)
        if len(samples) != ROWS_PER_DAY or samples[0].t != start or samples[-1].t != start + timedelta(days=1):
            raise SourceUnavailable("malformed_response", f"unexpected table span ({len(samples)} rows)")
        table = DayTable(body, city, local_date, samples, response)
        with self._lock:
            self._tables[key] = table
        return table

    def phase_table(self, city: City, instant: datetime) -> PhaseTable:
        """The hourly Moon-phase table for the city that covers ``instant`` (the plan window, or a
        10-day window around the instant for other dates)."""
        key = ("phase", city.name, PHASE_WINDOW)
        window = PHASE_WINDOW
        start = datetime.fromisoformat(PHASE_WINDOW[0]).replace(tzinfo=UTC)
        stop = datetime.fromisoformat(PHASE_WINDOW[1]).replace(tzinfo=UTC)
        t = instant.astimezone(UTC)
        if not start <= t <= stop:
            day = t.replace(hour=0, minute=0, second=0, microsecond=0)
            window = (f"{day - timedelta(days=5):%Y-%m-%d %H:%M}", f"{day + timedelta(days=5):%Y-%m-%d %H:%M}")
            key = ("phase", city.name, window)
        with self._lock:
            if key in self._phase:
                return self._phase[key]
        response = self.client.fetch(moon_phase_query(city, *window))
        try:
            samples = parse_phase_table(json.loads(response.text)["result"])
        except (HorizonsFormatError, KeyError, ValueError) as exc:
            raise SourceUnavailable("malformed_response", str(exc)) from exc
        table = PhaseTable(city, samples, response)
        with self._lock:
            self._phase[key] = table
        return table

    def moon_phase(self, city: City, instant: datetime) -> tuple[tuple[float, float, bool], PhaseTable]:
        table = self.phase_table(city, instant)
        return table.at(instant), table

    def separation(self, body_a: str, body_b: str, city: City, instant: datetime) -> float:
        a, _ = self.position(body_a, city, instant)
        b, _ = self.position(body_b, city, instant)
        return separation_deg(a.ra_deg, a.dec_deg, b.ra_deg, b.dec_deg)

    def position(self, body: str, city: City, instant: datetime) -> tuple[Position, DayTable]:
        local_date = instant.astimezone(city.tz).date()
        table = self.day_table(body, city, local_date)
        return table.position(instant), table

    def events(self, body: str, city: City, local_date: date) -> tuple[Events, DayTable]:
        table = self.day_table(body, city, local_date)
        return table.events(), table
