"""Golden tests: verified series vs values Arne computed by hand from 10-K filings
(values.toml).

Every value runs through metrics/verified.py, the same code path a page charts. A key in
values.toml with no verified series fails: that's the red step before implementing it.

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

from pricedin.metrics.verified import VERIFIED
from pricedin.normalize import edgar
from pricedin.normalize.schema import Statements
from pricedin.normalize.tags import CAPEX_SOFTWARE, CHAINS

HERE = Path(__file__).parent
GOLDEN = tomllib.loads((HERE / "values.toml").read_text())
TOLERANCE = 0.005  # relative; filings round differently
SCALE = {"usd": 1e6, "ratio": 0.01, "shares": 1e6}  # values.toml: millions; margins in %
CAPEX_PARTS = ("capex_ppe", "capex_software")  # summed into capex (DECISIONS #40)
MIN_COMPANIES = 3  # golden set: 3-5 companies across sectors


def periods():
    for ticker, company in GOLDEN.items():
        for key, values in company.items():
            if isinstance(values, dict):
                yield ticker, date.fromisoformat(key), values


def expected(values: dict) -> dict[str, float]:
    """Golden value per series name for one period."""
    parts = [p for p in CAPEX_PARTS if p in values]
    assert len(parts) in (0, len(CAPEX_PARTS)), f"capex needs all of {CAPEX_PARTS}: {parts}"
    assert not (parts and "capex" in values), "give capex or its parts, not both"
    out = {k: v for k, v in values.items() if k not in CAPEX_PARTS}
    if parts:
        out["capex"] = sum(values[p] for p in CAPEX_PARTS)
    return out


@cache
def statements(ticker: str) -> Statements:
    return edgar.statements((HERE / "fixtures" / f"{ticker}.json").read_bytes())


CASES = [
    pytest.param(t, end, name, value, id=f"{t}-{end}-{name}")
    for t, end, values in periods()
    for name, value in expected(values).items()
]


@pytest.mark.parametrize("ticker,end,name,value", CASES)
def test_golden(ticker, end, name, value):
    assert name in VERIFIED, f"no verified series {name!r}: add it to metrics/verified.py"
    series, s = VERIFIED[name], statements(ticker)
    actual = series.values(s).get(end)
    assert actual is not None, f"{name} for {end} not resolved"
    sources = [
        f"{f.source_tag} from {f.accession}"
        for f in (s.series(c).get(end) for c in series.inputs)
        if f
    ]
    assert actual / SCALE[series.unit] == pytest.approx(value, rel=TOLERANCE), sources


@pytest.mark.parametrize("name", list(VERIFIED))
def test_every_verified_series_has_golden_values(name):
    """The display gate: nothing enters VERIFIED on a token test."""
    companies = {t for t, _, values in periods() if name in expected(values)}
    assert len(companies) >= MIN_COMPANIES, f"{name}: golden values for {sorted(companies)}"


def test_fixtures_contain_every_chain_tag():
    """A chain tag missing from a fixture would silently skip it: regenerate fixtures."""
    chain_tags = {t for chain in CHAINS.values() for t in chain} | set(CAPEX_SOFTWARE)
    for ticker in GOLDEN:
        meta = json.loads((HERE / "fixtures" / f"{ticker}.json").read_text())["pricedin_fixture"]
        assert chain_tags <= set(meta["tags"]), f"{ticker}: run make_fixtures.py"
