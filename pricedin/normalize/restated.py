"""Which reported values count for an annual period (DECISIONS #10, #16, #27, #28).

companyfacts repeats a year's value in every later filing that reports it. Only 10-K and
10-K/A count, only full-year durations, and a filing's value counts only for its own last
three fiscal years (approximating "primary statements only").
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from pricedin.normalize.schema import Period

ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
# SEC frames treat 365 +/- 30 days as annual. Covers 52/53-week fiscal years.
ANNUAL_DAYS = range(335, 396)
# A filing's last 3 fiscal years end within ~2 years of its own year end.
WINDOW = timedelta(days=800)
# Starts this close together with the same end date are the same fiscal year.
SAME_START = timedelta(days=7)


def annual(entries: list[dict]) -> Iterator[tuple[Period, dict]]:
    """Full-year values from 10-K and 10-K/A filings, minus impossible future-dated ones."""
    for entry in entries:
        if entry.get("form") not in ANNUAL_FORMS or "start" not in entry:
            continue
        period = Period(date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"]))
        if period.days in ANNUAL_DAYS and period.end <= date.fromisoformat(entry["filed"]):
            yield period, entry


def filing_key(entry: dict) -> tuple[str, str]:
    """Orders filings by recency: filing date, then accession number."""
    return entry["filed"], entry["accn"]


def in_window(end: date, own_end: date) -> bool:
    """Is `end` one of the last three fiscal years of a filing about year `own_end`?"""
    return own_end - end <= WINDOW


def nominal_year(end: date) -> int:
    """Calendar year a fiscal year mostly covers: a 52/53-week year ending Jan 1-7 counts
    as the previous year."""
    return (end - timedelta(days=7)).year
