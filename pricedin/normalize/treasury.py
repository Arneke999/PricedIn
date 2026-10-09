"""Treasury yield-curve CSV -> the latest 10-year yield."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

TEN_YEAR = "10 Yr"


def latest_ten_year(body: bytes) -> tuple[date, float] | None:
    """The newest date with a 10-year yield, and the yield as a fraction (5.22% -> 0.0522)."""
    rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    found = []
    for row in rows:
        value = (row.get(TEN_YEAR) or "").strip()
        if value:
            day = datetime.strptime(row["Date"], "%m/%d/%Y").date()
            found.append((day, float(value) / 100))
    return max(found, default=None)
