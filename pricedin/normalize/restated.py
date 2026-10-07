"""Latest-restated pick for annual values (DECISIONS #10, #16).

companyfacts repeats a period's value in every later filing that reports it. For each
annual period, keep the value from the newest 10-K or 10-K/A.
"""

from __future__ import annotations

from datetime import date

from pricedin.normalize.schema import Period

ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
# SEC frames treat 365 +/- 30 days as annual. Covers 52/53-week fiscal years.
ANNUAL_DAYS = range(335, 396)


def latest_annual(entries: list[dict]) -> dict[Period, dict]:
    picked: dict[Period, dict] = {}
    for entry in entries:
        if entry.get("form") not in ANNUAL_FORMS or "start" not in entry:
            continue
        period = Period(date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"]))
        if period.days not in ANNUAL_DAYS:
            continue
        best = picked.get(period)
        if best is None or (entry["filed"], entry["accn"]) > (best["filed"], best["accn"]):
            picked[period] = entry
    return picked
