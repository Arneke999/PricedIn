"""Verified series: the only numbers a page may chart (display gate, DECISIONS #17, #42-#43).

A series goes in VERIFIED only once its golden test passes. tests/golden checks every entry
against Arne's hand-computed values through this same dict, so a chart and its golden test
run one code path. An entry without golden values for at least three companies fails
tests/golden/test_golden.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pricedin.metrics.cash_flow import free_cash_flow
from pricedin.metrics.margins import operating_margin
from pricedin.normalize.schema import Fact, Statements


def line_item(series: dict[date, Fact]) -> dict[date, float]:
    """A canonical line item as reported, no arithmetic."""
    return {e: f.value for e, f in series.items()}


@dataclass(frozen=True)
class Series:
    inputs: tuple[str, ...]  # canonical concepts, passed to compute in this order
    compute: Callable[..., dict[date, float]]
    unit: Literal["usd", "ratio"]

    def values(self, stmts: Statements) -> dict[date, float]:
        return self.compute(*(stmts.series(c) for c in self.inputs))


VERIFIED: dict[str, Series] = {
    "revenue": Series(("revenue",), line_item, "usd"),
    "operating_income": Series(("operating_income",), line_item, "usd"),
    "operating_cash_flow": Series(("operating_cash_flow",), line_item, "usd"),
    "capex": Series(("capex",), line_item, "usd"),
    "operating_margin": Series(("revenue", "operating_income"), operating_margin, "ratio"),
    "fcf": Series(("operating_cash_flow", "capex"), free_cash_flow, "usd"),
}
