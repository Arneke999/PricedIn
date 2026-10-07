"""Margin metrics.

Phase 0a skeleton: no golden test yet, so these render only under the page-wide
"unverified" banner (DECISIONS #17).
"""

from __future__ import annotations

from pricedin.normalize.schema import Fact, Period


def operating_margin(
    revenue: dict[Period, Fact], operating_income: dict[Period, Fact]
) -> dict[Period, float]:
    """Operating income / revenue, for periods where both exist and revenue is non-zero."""
    periods = sorted(revenue.keys() & operating_income.keys())
    return {p: operating_income[p].value / revenue[p].value for p in periods if revenue[p].value}
