"""Margin metrics.

Golden-tested (tests/golden). A page charts them only through metrics/verified.py.
"""

from __future__ import annotations

from datetime import date

from pricedin.normalize.schema import Fact


def operating_margin(
    revenue: dict[date, Fact], operating_income: dict[date, Fact]
) -> dict[date, float]:
    """Operating income / revenue, for years where both exist and revenue is positive
    (DECISIONS #23: no margins on zero or negative revenue)."""
    ends = sorted(revenue.keys() & operating_income.keys())
    return {e: operating_income[e].value / revenue[e].value for e in ends if revenue[e].value > 0}
