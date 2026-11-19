"""Tools against the committed Horizons fixtures (offline), including the failure path."""

import pytest

from cielo_bench.domains.astronomy.horizons import CREDIT

SATURN_2100 = {"body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"}
FAILURE_KEYS = {"status", "source", "reason", "message"}


def test_body_position_matches_horizons_row(executor):
    r = executor.execute("body_position", SATURN_2100)
    assert r["status"] == "ok"
    assert r["altitude_deg"] == pytest.approx(61.63, abs=0.01)  # Horizons Elev_(r-app) 61.633823
    assert r["azimuth_deg"] == pytest.approx(260.07, abs=0.01)
    assert r["above_horizon"] is True and r["interpolated"] is False
    assert r["datetime_utc"] == "2026-12-13T02:00:00Z"
    src = r["sources"][0]
    assert src["service"] == "NASA/JPL Horizons API" and len(src["response_sha256"]) == 64
    assert r["credit"] == CREDIT


def test_same_instant_in_utc_or_naive_local_gives_same_values(executor):
    a = executor.execute("body_position", SATURN_2100)
    b = executor.execute("body_position", {**SATURN_2100, "datetime": "2026-12-13T02:00:00Z"})
    c = executor.execute("body_position", {**SATURN_2100, "datetime": "2026-12-12T21:00"})
    assert a["altitude_deg"] == b["altitude_deg"] == c["altitude_deg"]


def test_spanish_and_unaccented_names_are_accepted(executor):
    r = executor.execute(
        "body_position", {"body": "Saturno", "location": {"city": "medellin"}, "datetime": "2026-12-12T21:00:00-05:00"}
    )
    assert r["status"] == "ok" and r["body"] == "Saturn"


def test_interpolation_between_minutes(executor):
    r = executor.execute("body_position", {**SATURN_2100, "datetime": "2026-12-12T21:00:30-05:00"})
    assert r["status"] == "ok" and r["interpolated"] is True


def test_rise_set(executor):
    r = executor.execute("body_rise_set", {"body": "Saturn", "location": {"city": "Medellín"}, "date": "2026-12-12"})
    assert r["status"] == "ok"
    assert r["rise"]["local_time"] == "13:07"
    assert r["set"]["local_time"] == "01:14"
    assert r["culmination"]["local_time"] == "19:09"
    assert r["culmination"]["altitude_deg"] == pytest.approx(84.57, abs=0.05)
    assert "crosses 0 degrees" in r["definition"]


@pytest.mark.parametrize(
    "name,args,status",
    [
        ("body_position", {**SATURN_2100, "body": "Pluto"}, "invalid_input"),
        ("body_position", {**SATURN_2100, "location": {"city": "Paris"}}, "invalid_input"),
        ("body_position", {**SATURN_2100, "datetime": "tonight"}, "invalid_input"),
        ("body_rise_set", {"body": "Saturn", "location": {"city": "Medellín"}, "date": "12/12/2026"}, "invalid_input"),
        ("body_position", None, "invalid_input"),
        ("weather", {}, "out_of_scope"),
    ],
)
def test_invalid_inputs(executor, name, args, status):
    assert executor.execute(name, args)["status"] == status


def test_cache_miss_offline_is_source_unavailable_with_no_values(executor):
    r = executor.execute("body_position", {**SATURN_2100, "datetime": "2030-01-01T21:00:00-05:00"})
    assert r["status"] == "source_unavailable"
    assert set(r) <= FAILURE_KEYS


@pytest.mark.parametrize("profile", ["down", "error", "empty"])
@pytest.mark.parametrize(
    "name,args",
    [
        ("body_position", SATURN_2100),
        ("body_rise_set", {"body": "Saturn", "location": {"city": "Medellín"}, "date": "2026-12-12"}),
    ],
)
def test_source_down_returns_no_invented_values(domain, profile, name, args):
    faulty = domain.make_executor(fault_profile=profile)
    r = faulty.execute(name, args)
    assert r["status"] == "source_unavailable"
    assert set(r) <= FAILURE_KEYS  # no altitude, no times, nothing partial
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r.values())


def test_relative_to_gives_the_separation_from_both_positions(executor):
    from cielo_bench.domains.astronomy.ephemeris import separation_deg

    r = executor.execute("body_position", {**SATURN_2100, "relative_to": "Jupiter"})
    jupiter = executor.execute("body_position", {**SATURN_2100, "body": "Jupiter"})
    assert r["status"] == "ok" and r["relative_to"] == "Jupiter"
    expected = separation_deg(15 * r["ra_hours"], r["dec_deg"], 15 * jupiter["ra_hours"], jupiter["dec_deg"])
    assert r["separation_deg"] == pytest.approx(expected, abs=0.01)
    assert len(r["sources"]) == 2
    assert executor.execute("body_position", {**SATURN_2100, "relative_to": "Saturn"})["status"] == "invalid_input"
    assert executor.execute("body_position", {**SATURN_2100, "relative_to": "Pluto"})["status"] == "invalid_input"


def test_altitude_rate_and_rise_azimuth(executor):
    # Saturn culminates at 19:08 on 12 December 2026, so at 21:00 it is getting lower.
    assert executor.execute("body_position", SATURN_2100)["altitude_rate_deg_per_hour"] < 0
    early = executor.execute("body_position", {**SATURN_2100, "datetime": "2026-12-12T18:00:00-05:00"})
    assert early["altitude_rate_deg_per_hour"] > 0
    r = executor.execute("body_rise_set", {"body": "Saturn", "location": {"city": "Medellín"}, "date": "2026-12-12"})
    assert 60 < r["rise"]["azimuth_deg"] < 120 and 240 < r["set"]["azimuth_deg"] < 300


def test_moon_phase(executor):
    r = executor.execute("moon_phase", {"location": {"city": "Medellín"}, "datetime": "2026-12-26T19:30:00-05:00"})
    assert r["status"] == "ok" and r["phase"] == "waning"
    assert r["illuminated_fraction_pct"] == pytest.approx(86.86, abs=0.05)
    assert 130 < r["sun_moon_elongation_deg"] < 145 and r["sources"][0]["query"]["QUANTITIES"] == "'10,23'"
    waxing = executor.execute("moon_phase", {"location": {"city": "Bogotá"}, "datetime": "2027-03-13T20:00"})
    assert waxing["phase"] == "waxing"
    assert (
        executor.execute("moon_phase", {"location": {"city": "Lima"}, "datetime": "2027-03-13T20:00"})["status"]
        == "invalid_input"
    )
    assert (
        executor.execute("moon_phase", {"location": {"city": "Bogotá"}, "datetime": "soon"})["status"]
        == "invalid_input"
    )
    outside = executor.execute("moon_phase", {"location": {"city": "Bogotá"}, "datetime": "2030-01-01T20:00"})
    assert outside["status"] == "source_unavailable" and set(outside) <= FAILURE_KEYS


@pytest.mark.parametrize("profile", ["down", "error", "empty"])
def test_moon_phase_source_down_returns_no_values(domain, profile):
    r = domain.make_executor(fault_profile=profile).execute(
        "moon_phase", {"location": {"city": "Medellín"}, "datetime": "2026-12-26T19:30:00-05:00"}
    )
    assert r["status"] == "source_unavailable" and set(r) <= FAILURE_KEYS
