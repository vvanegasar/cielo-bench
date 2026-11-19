"""A plausible *wrong* version of a reference query, for the simulated model.

The perturbation keeps the query's shape and changes the item it asks about, the way a
careless analyst would: the neighbouring invoice number, SKU or customer id, or else every
date one year earlier (the same month or quarter of the previous year). The build makes
facts unique among such siblings, so a perturbed query does not establish the fact.
"""

from __future__ import annotations

import re

_INVOICE = re.compile(r"'INV-(\d{4})-(\d{5})'")
_SKU = re.compile(r"'([A-Z]{3})-(\d{4})'")
_CUSTOMER = re.compile(r"(\bcustomer_id\s*=\s*)(\d+)\b")
_DATE = re.compile(r"'(\d{4})-(\d{2})-(\d{2})'")


def perturb_sql(sql: str) -> str | None:
    if _INVOICE.search(sql):
        return _INVOICE.sub(lambda m: f"'INV-{m.group(1)}-{int(m.group(2)) + 1:05d}'", sql)
    if _SKU.search(sql):
        return _SKU.sub(lambda m: f"'{m.group(1)}-{int(m.group(2)) + 1:04d}'", sql)
    if _CUSTOMER.search(sql):
        return _CUSTOMER.sub(lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", sql)
    if _DATE.search(sql):
        return _DATE.sub(lambda m: f"'{int(m.group(1)) - 1}-{m.group(2)}-{m.group(3)}'", sql)
    return None
