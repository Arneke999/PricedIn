"""Return on invested capital (DECISIONS #53-#57, #64).

Invested capital at a fiscal year-end = equity + debt − cash and short-term investments
(financing side; goodwill stays in, operating leases stay out). ROIC = NOPAT ÷ the average of
the opening and closing invested capital, where NOPAT = operating income × (1 − tax rate), and
an operating loss is not taxed (DECISIONS #68).
"""

from __future__ import annotations

from datetime import date, timedelta

from pricedin.normalize.schema import Fact, Period

# US federal statutory rate before and after the 2017 tax reform (DECISIONS #56)
STATUTORY_BEFORE, STATUTORY_AFTER = 0.35, 0.21
TAX_REFORM = date(2018, 1, 1)
# An effective rate outside this range is not a usable estimate of operating taxes.
USABLE_RATE = (0.0, 0.5)
# The opening balance is the year-end this close before the fiscal year starts.
OPENING_GAP = timedelta(days=7)


def statutory_rate(period: Period) -> float:
    """The federal rate in force over a fiscal year, days-weighted across 2018-01-01."""
    if period.end < TAX_REFORM:
        return STATUTORY_BEFORE
    if period.start >= TAX_REFORM:
        return STATUTORY_AFTER
    before = (TAX_REFORM - period.start).days
    return (STATUTORY_BEFORE * before + STATUTORY_AFTER * (period.days - before)) / period.days


def tax_rate(period: Period, income_tax: Fact | None, pretax_income: Fact | None) -> float | None:
    """The effective rate, or None when it's unusable: pretax income ≤ 0, a rate outside
    0–50%, or either input missing."""
    if income_tax is None or pretax_income is None or pretax_income.value <= 0:
        return None
    rate = income_tax.value / pretax_income.value
    return rate if USABLE_RATE[0] <= rate <= USABLE_RATE[1] else None


def statutory_years(
    operating_income: dict[date, Fact],
    income_tax: dict[date, Fact],
    pretax_income: dict[date, Fact],
) -> list[date]:
    """Profitable fiscal years whose NOPAT uses the statutory rate because the effective one
    is unusable."""
    return [
        end
        for end, fact in operating_income.items()
        if fact.value >= 0
        and tax_rate(fact.period, income_tax.get(end), pretax_income.get(end)) is None
    ]


def loss_years(operating_income: dict[date, Fact]) -> list[date]:
    """Fiscal years with an operating loss, which isn't taxed (DECISIONS #68)."""
    return [end for end, fact in operating_income.items() if fact.value < 0]


def invested_capital(
    equity: dict[date, Fact], debt: dict[date, Fact], cash: dict[date, Fact]
) -> dict[date, float]:
    """Equity + debt − cash and short-term investments at each year-end with equity and cash.
    A year-end with no debt reported has no debt (DECISIONS #64)."""
    ends = sorted(equity.keys() & cash.keys())
    return {
        e: equity[e].value + (debt[e].value if e in debt else 0.0) - cash[e].value for e in ends
    }


def roic(
    operating_income: dict[date, Fact],
    income_tax: dict[date, Fact],
    pretax_income: dict[date, Fact],
    equity: dict[date, Fact],
    debt: dict[date, Fact],
    cash: dict[date, Fact],
) -> dict[date, float]:
    """NOPAT ÷ average invested capital, for fiscal years with both an opening and a closing
    balance and a positive average (DECISIONS #53)."""
    capital = invested_capital(equity, debt, cash)
    out = {}
    for end, fact in sorted(operating_income.items()):
        opening = max((e for e in capital if e < end), default=None)
        if end not in capital or opening is None or fact.period.start - opening > OPENING_GAP:
            continue
        average = (capital[opening] + capital[end]) / 2
        if average <= 0:
            continue
        if fact.value < 0:
            rate = 0.0
        else:
            rate = tax_rate(fact.period, income_tax.get(end), pretax_income.get(end))
            if rate is None:
                rate = statutory_rate(fact.period)
        out[end] = fact.value * (1 - rate) / average
    return out
