"""Latest-restated pick for annual values (DECISIONS #10, #16).

companyfacts repeats a period's value in every later filing that reports it. For each
annual period, the newest 10-K or 10-K/A wins.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from pricedin.normalize.schema import Period

ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
# SEC frames treat 365 +/- 30 days as annual. Covers 52/53-week fiscal years.
ANNUAL_DAYS = range(335, 396)


def annual(entries: list[dict]) -> Iterator[tuple[Period, dict]]:
    """Full-year values from 10-K and 10-K/A filings."""
    for entry in entries:
        if entry.get("form") not in ANNUAL_FORMS or "start" not in entry:
            continue
        period = Period(date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"]))
        if period.days in ANNUAL_DAYS:
            yield period, entry


def filing_key(entry: dict) -> tuple[str, str]:
    """Orders filings by recency: filing date, then accession number."""
    return entry["filed"], entry["accn"]
