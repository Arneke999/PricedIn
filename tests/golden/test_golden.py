"""Golden tests: canonical line items and metrics vs values Arne computed by hand from
10-K filings (values.toml).

Hard rule 3: a failure means the code or a definition is wrong, never the expected value.
Each test runs against a pinned companyfacts snapshot (fixtures/, see make_fixtures.py).
"""

from __future__ import annotations

import json
import tomllib
from datetime import date
from functools import cache
from pathlib import Path

import pytest

from pricedin.metrics.cash_flow import free_cash_flow
from pricedin.metrics.margins import operating_margin
from pricedin.normalize import edgar
from pricedin.normalize.schema import Statements
from pricedin.normalize.tags import CAPEX_SOFTWARE, CHAINS

HERE = Path(__file__).parent
GOLDEN = tomllib.loads((HERE / "values.toml").read_text())
TOLERANCE = 0.005  # relative; filings round differently
LINE_ITEMS = ("revenue", "operating_income", "operating_cash_flow", "capex")


def periods():
    for ticker, company in GOLDEN.items():
        for key, values in company.items():
            if isinstance(values, dict):
                yield ticker, date.fromisoformat(key), values


def expected_capex(values: dict) -> float | None:
    if "capex" in values:
        return values["capex"]
    if "capex_ppe" in values:
        return values["capex_ppe"] + values["capex_software"]
    return None


@cache
def statements(ticker: str) -> Statements:
    return edgar.statements((HERE / "fixtures" / f"{ticker}.json").read_bytes())


LINE_CASES = [
    pytest.param(t, end, item, id=f"{t}-{end}-{item}")
    for t, end, values in periods()
    for item in LINE_ITEMS
    if (expected_capex(values) if item == "capex" else values.get(item)) is not None
]


@pytest.mark.parametrize("ticker,end,item", LINE_CASES)
def test_line_item(ticker, end, item):
    values = dict(periods_by_key()[(ticker, end)])
    expected = expected_capex(values) if item == "capex" else values[item]
    fact = statements(ticker).series(item).get(end)
    assert fact is not None, f"{item} for {end} not resolved"
    assert fact.value / 1e6 == pytest.approx(expected, rel=TOLERANCE), (
        f"{fact.source_tag} from {fact.accession}"
    )


@pytest.mark.parametrize(
    "ticker,end",
    [pytest.param(t, e, id=f"{t}-{e}") for t, e, v in periods() if "operating_margin" in v],
)
def test_operating_margin(ticker, end):
    s = statements(ticker)
    margin = operating_margin(s.series("revenue"), s.series("operating_income")).get(end)
    assert margin is not None
    expected = periods_by_key()[(ticker, end)]["operating_margin"]
    assert margin * 100 == pytest.approx(expected, rel=TOLERANCE)


@pytest.mark.parametrize(
    "ticker,end", [pytest.param(t, e, id=f"{t}-{e}") for t, e, v in periods() if "fcf" in v]
)
def test_free_cash_flow(ticker, end):
    s = statements(ticker)
    fcf = free_cash_flow(s.series("operating_cash_flow"), s.series("capex")).get(end)
    assert fcf is not None
    expected = periods_by_key()[(ticker, end)]["fcf"]
    assert fcf / 1e6 == pytest.approx(expected, rel=TOLERANCE)


def test_fixtures_contain_every_chain_tag():
    """A chain tag missing from a fixture would silently skip it: regenerate fixtures."""
    chain_tags = {t for chain in CHAINS.values() for t in chain} | set(CAPEX_SOFTWARE)
    for ticker in GOLDEN:
        meta = json.loads((HERE / "fixtures" / f"{ticker}.json").read_text())["pricedin_fixture"]
        assert chain_tags <= set(meta["tags"]), f"{ticker}: run make_fixtures.py"


@cache
def periods_by_key() -> dict:
    return {(t, end): values for t, end, values in periods()}
