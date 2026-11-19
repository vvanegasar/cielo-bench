"""Helpers for the astronomy tests: synthetic Horizons responses. No network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HEADER = " Date__(UT)__HR:MN, , , R.A._(ICRF), DEC_(ICRF), Azi_(r-app), Elev_(r-app),             delta,     deldot,"


def horizons_body(start: datetime, minutes: int, el_fn, az_fn=lambda i: 90.0, marker_fn=lambda i: "") -> bytes:
    rows = []
    for i in range(minutes + 1):
        t = start + timedelta(minutes=i)
        rows.append(
            f" {t.year}-{MONTHS[t.month - 1]}-{t.day:02d} {t.hour:02d}:{t.minute:02d}, ,{marker_fn(i)},"
            f"    10.00000,    5.00000,  {az_fn(i):.6f},  {el_fn(i):.6f},  1.00000000000000,  0.0000000,"
        )
    result = "\n".join(
        ["Ephemeris (synthetic test data)", "*" * 40, HEADER, "*" * 40, "$$SOE", *rows, "$$EOE", "*" * 40]
    )
    return json.dumps({"signature": {"source": "NASA/JPL Horizons API", "version": "1.2"}, "result": result}).encode()


__all__ = ["UTC", "horizons_body"]
