import json
import math
from datetime import date, datetime, timedelta

import pytest
from astro_support import UTC, horizons_body

from cielo_bench.cache import CachedResponse
from cielo_bench.domains.astronomy.ephemeris import DayTable, HorizonsFormatError, parse_observer_table
from cielo_bench.domains.astronomy.sky import CITIES

START = datetime(2026, 12, 12, 5, 0, tzinfo=UTC)


def table(el_fn, az_fn=lambda i: 90.0, minutes=1440, marker_fn=lambda i: ""):
    body = horizons_body(START, minutes, el_fn, az_fn, marker_fn)
    samples = parse_observer_table(json.loads(body)["result"])
    src = CachedResponse("k", "e", {}, body, "sha", "t")
    return DayTable("Saturn", CITIES["Medellín"], date(2026, 12, 12), samples, src)


def test_rise_set_and_culmination_on_a_known_curve():
    # elevation = 40 sin(2 pi (i - 300) / 1440): rises at i = 300, culminates at 660, sets at 1020
    t = table(lambda i: 40 * math.sin(2 * math.pi * (i - 300.4) / 1440))
    ev = t.events()
    assert abs((ev.rise - (START + timedelta(minutes=300.4))).total_seconds()) < 2
    assert abs((ev.set - (START + timedelta(minutes=1020.4))).total_seconds()) < 2
    assert abs((ev.culmination - (START + timedelta(minutes=660.4))).total_seconds()) < 2
    assert ev.culmination_altitude_deg == pytest.approx(40, abs=0.01)
    assert ev.n_rises == 1 and ev.n_sets == 1


def test_no_rise_when_always_below():
    ev = table(lambda i: -5.0 - i / 1000).events()
    assert ev.rise is None and ev.set is None


def test_exact_minute_and_interpolated_positions():
    t = table(lambda i: float(i) / 10)
    exact = t.position(START + timedelta(minutes=100))
    assert exact.altitude_deg == pytest.approx(10.0) and exact.interpolated is False
    half = t.position(START + timedelta(minutes=100, seconds=30))
    assert half.altitude_deg == pytest.approx(10.05) and half.interpolated is True


def test_azimuth_interpolation_wraps_through_north():
    t = table(lambda i: 20.0, az_fn=lambda i: 359.5 if i % 2 == 0 else 0.5)
    mid = t.position(START + timedelta(seconds=30))
    assert min(mid.azimuth_deg, 360 - mid.azimuth_deg) == pytest.approx(0.0, abs=1e-6)


def test_jpl_markers_are_kept_as_cross_check():
    ev = table(lambda i: 10.0, marker_fn=lambda i: "r" if i == 5 else "").events()
    assert ev.jpl_markers == {"r": ["2026-12-12T05:05:00Z"]}


def test_outside_the_table_raises():
    with pytest.raises(ValueError):
        table(lambda i: 1.0).position(START - timedelta(minutes=1))


def test_non_numeric_value_is_a_format_error():
    body = horizons_body(START, 2, lambda i: 1.0).decode().replace("1.000000,  1.0000", "n.a.,  1.0000", 1)
    with pytest.raises(HorizonsFormatError):
        parse_observer_table(json.loads(body)["result"])


def test_missing_markers_is_a_format_error():
    with pytest.raises(HorizonsFormatError):
        parse_observer_table("no table at all")
