from datetime import date

import pytest

from pricedin.metrics.returns import invested_capital, roic, statutory_rate, statutory_years
from pricedin.normalize.schema import Fact, Period


def fact(concept, year, value, start=None, end=None):
    end = end or date(year, 12, 31)
    period = Period(start or (end if concept in BALANCES else date(year, 1, 1)), end)
    return Fact(concept, period, value, "USD", "Tag", "a", "10-K", date(year + 1, 2, 1), 1)


BALANCES = {"equity", "debt", "cash"}


def series(concept, values):
    return {f.period.end: f for f in (fact(concept, y, v) for y, v in values.items())}


def test_statutory_rate_follows_the_2017_tax_reform():
    assert statutory_rate(Period(date(2017, 1, 1), date(2017, 12, 31))) == 0.35
    assert statutory_rate(Period(date(2018, 1, 1), date(2018, 12, 31))) == 0.21
    # MSFT-style fiscal year July 2017 - June 2018: 184 days at 35%, 180 at 21%
    blended = statutory_rate(Period(date(2017, 7, 1), date(2018, 6, 30)))
    assert blended == pytest.approx((0.35 * 184 + 0.21 * 180) / 364)


def test_no_debt_reported_counts_as_none():
    capital = invested_capital(series("equity", {2023: 100}), {}, series("cash", {2023: 30}))
    assert capital == {date(2023, 12, 31): 70}


def balances(**years):
    """equity, debt, cash per year; average capital 100 for 2024 by default."""
    return (
        series("equity", {2023: 100, 2024: 120, **years.get("equity", {})}),
        series("debt", {2023: 20, 2024: 20}),
        series("cash", {2023: 30, 2024: 30, **years.get("cash", {})}),
    )


def test_roic_uses_the_effective_rate_on_average_capital():
    result = roic(
        series("operating_income", {2024: 50}),
        series("income_tax", {2024: 10}),
        series("pretax_income", {2024: 40}),
        *balances(),
    )
    # NOPAT 50 x (1 - 0.25) = 37.5; capital (90 + 110) / 2 = 100
    assert result == {date(2024, 12, 31): pytest.approx(0.375)}


@pytest.mark.parametrize("tax,pretax", [(10, -5), (30, 40), (-2, 40), (None, 40)])
def test_unusable_effective_rate_falls_back_to_statutory(tax, pretax):
    income_tax = series("income_tax", {2024: tax}) if tax is not None else {}
    args = (series("operating_income", {2024: 50}), income_tax)
    args += (series("pretax_income", {2024: pretax}),)
    assert roic(*args, *balances()) == {date(2024, 12, 31): pytest.approx(50 * 0.79 / 100)}
    assert statutory_years(*args) == [date(2024, 12, 31)]


def test_no_roic_without_an_opening_balance():
    equity, debt, cash = balances()
    del equity[date(2023, 12, 31)]
    result = roic(
        series("operating_income", {2024: 50}),
        series("income_tax", {2024: 10}),
        series("pretax_income", {2024: 40}),
        equity,
        debt,
        cash,
    )
    assert result == {}


def test_no_roic_when_average_capital_is_not_positive():
    result = roic(
        series("operating_income", {2024: 50}),
        series("income_tax", {2024: 10}),
        series("pretax_income", {2024: 40}),
        *balances(cash={2023: 200, 2024: 200}),
    )
    assert result == {}


def test_no_roic_across_a_missing_year_end():
    equity, debt, cash = balances()
    for s in (equity, debt, cash):
        s[date(2022, 12, 31)] = s.pop(date(2023, 12, 31))
    result = roic(
        series("operating_income", {2024: 50}),
        series("income_tax", {2024: 10}),
        series("pretax_income", {2024: 40}),
        equity,
        debt,
        cash,
    )
    assert result == {}


def test_an_operating_loss_is_not_taxed():
    args = (
        series("operating_income", {2024: -50}),
        series("income_tax", {2024: -5}),
        series("pretax_income", {2024: -60}),
    )
    assert roic(*args, *balances()) == {date(2024, 12, 31): pytest.approx(-0.5)}
    assert statutory_years(*args) == []
