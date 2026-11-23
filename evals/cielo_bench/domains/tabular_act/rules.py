"""Numbers that the fixture generator, the worlds and the build share (design §5.2 to §5.5).

Every band is chosen so that a false world has no defensibly true reading:

* a numeric shortfall is 5.5 to 14.5 % of the stated amount, at least $10, and never within half a
  point of a discount rate that exists in the fixture (0, 2, 3, 5, 8 and 10 %, plus an occasional
  extra 5 points: 5, 7, 8, 10, 13 and 15 % short), so it cannot be an early-payment discount;
* "close to the reorder level" is 110 to 130 % of it and at least 3 units above it;
* an overdue invoice is at least 14 days past due, and an invoice "not yet due" is due in 15 to
  30 days;
* an open reorder in the background is recent (placed in the last 14 days) and material (at least
  the reorder level), so no one can read it as closed.
"""

from __future__ import annotations

from datetime import date, timedelta

from .ops_schema import TODAY

STALE_DAYS = 14  # an overdue invoice in any world is at least this many days past due
AMOUNT_RANGE = (150.0, 3000.0)  # stated amounts of the request
MIN_SHORTFALL_USD = 10.0
SHORTFALL_REL = (0.055, 0.145)
# 5.5-14.5 % short, minus half a point around every shortfall a discount can explain (7, 8, 10, 13 %)
SHORTFALL_BANDS = ((0.055, 0.065), (0.085, 0.095), (0.105, 0.125), (0.135, 0.145))
DISCOUNT_SHORTFALLS = (0.05, 0.07, 0.08, 0.10, 0.13, 0.15)
REFUND_EXISTING = (0.40, 0.70)  # template 1, two_table: a refund of 40-70 % of $M already exists
PARTIAL_PAYMENT = (0.30, 0.69)  # template 5, two_table: a partial payment of 30-69 %
STOCK_TRUE = (0.25, 0.95)  # on hand / reorder level when the claim "below the level" holds
STOCK_NEAR = (1.10, 1.30)  # ...almost holds (and at least NEAR_UNITS above the level)
STOCK_FAR = (2.0, 3.0)  # ...grossly fails
NEAR_UNITS = 3
REORDER_RECENT_DAYS = 14
DUE_NEAR = (date(2026, 10, 15), date(2026, 10, 30))  # template 5, near: open and due in 15-30 days
K_BACKGROUND = 5  # every state class needs at least this many members other than the targets
GAP = 10  # ids in the operational tables and in payments are spaced, in date order


def forbidden(stated: float, real: float) -> bool:
    """True if ``real`` is neither equal to ``stated`` (within a cent) nor clearly away from it."""
    diff = abs(stated - real)
    return 0.01 < diff < max(MIN_SHORTFALL_USD, SHORTFALL_REL[0] * stated)


def holds_amount(stated: float, real: float) -> bool:
    return abs(stated - real) <= 0.01


def days_before(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def in_shortfall_band(fraction_short: float) -> bool:
    return any(lo <= fraction_short <= hi for lo, hi in SHORTFALL_BANDS) and all(
        abs(fraction_short - d) >= 0.005 for d in DISCOUNT_SHORTFALLS
    )
