"""Pages chart only verified series (display gate, DECISIONS #17, #42)."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from pricedin import config
from pricedin.data import archive, edgar
from pricedin.metrics.verified import VERIFIED
from pricedin.normalize import edgar as normalize_edgar
from pricedin.normalize.schema import Break, Fact, Period, Split, Stale, Statements
from pricedin.web.app import COMPANY_CHARTS, _chart, _warnings, app

KO_FIXTURE = Path(__file__).parent / "golden" / "fixtures" / "KO.json"
KO_CIK = 21344


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("PRICEDIN_RAW_DIR", str(tmp_path))
    tickers = {"0": {"cik_str": KO_CIK, "ticker": "KO", "title": "COCA COLA CO"}}
    archive.store(edgar.TICKERS_KIND, edgar.TICKERS_URL, json.dumps(tickers).encode())
    archive.store(edgar.companyfacts_kind(KO_CIK), "fixture", KO_FIXTURE.read_bytes())
    return app.test_client()


def test_company_page_charts_only_verified_series():
    assert {name for name, *_ in COMPANY_CHARTS} <= VERIFIED.keys()


def test_company_page_renders_its_charts_without_a_banner(client):
    html = client.get("/company/KO").get_data(as_text=True)
    charts = re.findall(r'<div id="([^"]+)" class="chart">', html)
    assert charts == [name for name, *_ in COMPANY_CHARTS]
    assert "nverified" not in html


def test_company_page_charts_the_verified_values(client):
    html = client.get("/company/KO").get_data(as_text=True)
    charts = json.loads(re.search(r"const charts = (.*);\n", html).group(1))
    stmts = normalize_edgar.statements(KO_FIXTURE.read_bytes())
    for chart in charts:
        values = VERIFIED[chart["id"]].values(stmts)
        points = [p for p in chart["points"] if p["value"] is not None]
        assert [(p["end"], p["value"]) for p in points] == [
            (end.isoformat(), value) for end, value in values.items()
        ]


def test_coverage_page_names_line_items_without_a_golden_test(client, monkeypatch):
    monkeypatch.delitem(VERIFIED, "net_income")
    html = client.get("/company/KO/coverage").get_data(as_text=True)
    note = re.search(r"No golden test yet for:\s+([^.]+)\.", html)
    assert note is not None
    untested = note.group(1).split(", ")
    assert "net income" in untested
    assert "revenue" not in untested


def test_stale_warning_names_related_tags_without_their_values():
    """Hint tags sit outside every chain, so their values stay on the coverage page (#46)."""
    end = date(2023, 12, 31)
    period = Period(date(2023, 1, 1), end)
    used = Fact("revenue", period, 5e9, "USD", "Revenues", "a", "10-K", date(2024, 2, 1), 1)
    stale = Stale("revenue", end, used, "b", date(2025, 2, 1), (("RevenuesNetOfX", 7.3e9),))
    stmts = Statements(cik=1, name="Test Co", facts={"revenue": {end: used}}, stale=[stale])
    [note] = _warnings(stmts, {"revenue"}, {end})
    assert "RevenuesNetOfX" in note
    assert "$7.3B" not in note


def fact(concept, year, value, unit="USD", split_factor=1.0, start=None, end=None) -> Fact:
    period = Period(start or date(year, 1, 1), end or date(year, 12, 31))
    filed = date(year + 1, 2, 1)
    return Fact(concept, period, value, unit, "Tag", "a", "10-K", filed, 1, split_factor)


def statements(*facts: Fact, **kwargs) -> Statements:
    by_concept: dict = {}
    for f in facts:
        by_concept.setdefault(f.concept, {})[f.period.end] = f
    return Statements(cik=1, name="Test Co", facts=by_concept, **kwargs)


def test_missing_years_are_empty_slots_with_a_warning():
    stmts = statements(
        fact("revenue", 2014, 1e9), fact("revenue", 2015, 2e9), fact("revenue", 2022, 3e9)
    )
    chart = _chart(stmts, "revenue", "Revenue", "bar", None)
    assert [p["label"] for p in chart["points"]] == [f"FY{y}" for y in range(2014, 2023)]
    assert [p["value"] for p in chart["points"]][1:3] == [2e9, None]
    [warning] = chart["warnings"]
    assert warning.startswith("No data for FY2016–FY2021. Years on either side")


def test_fiscal_year_end_change_is_not_a_gap():
    # A March year end, then a switch to December: about 21 months apart, no year missing.
    march = fact("revenue", 2020, 1e9, start=date(2019, 4, 1), end=date(2020, 3, 31))
    chart = _chart(statements(march, fact("revenue", 2021, 2e9)), "revenue", "Revenue", "bar", None)
    assert [p["label"] for p in chart["points"]] == ["FY2020", "FY2021"]
    assert chart["warnings"] == []


def test_split_adjusted_years_are_explained_with_their_cumulative_ratio():
    shares = [
        fact("diluted_shares", 2021, 28e9, "shares", split_factor=28),
        fact("diluted_shares", 2022, 24e9, "shares", split_factor=4),
        fact("diluted_shares", 2023, 20e9, "shares"),
    ]
    split = Split("diluted_shares", date(2022, 12, 31), 7.0, shares[0], shares[1])
    stmts = statements(*shares, splits=[split])
    chart = _chart(stmts, "diluted_shares", "Diluted shares", "line", None)
    [note] = chart["warnings"]
    assert note.startswith("Split-adjusted diluted shares: FY2021 28:1, FY2022 4:1, so earlier")
    assert "Splits found: 7:1 (the 10-K filed 2023-02-01 restated FY2022" in note
    assert chart["points"][0]["sources"][0].endswith(", split-adjusted 28:1")


def test_share_counts_in_warnings_are_shares_not_dollars():
    before = fact("diluted_shares", 2023, 100e6, "shares")
    after = fact("diluted_shares", 2023, 130e6, "shares")
    brk = Break("diluted_shares", date(2023, 12, 31), date(2022, 12, 31), before, after)
    [note] = _warnings(statements(after, breaks=[brk]), {"diluted_shares"}, {after.period.end})
    assert "from 100M shares to 130M shares" in note
    assert "$" not in note


def roic_chart(client):
    html = client.get("/company/KO").get_data(as_text=True)
    charts = json.loads(re.search(r"const charts = (.*);\n", html).group(1))
    return next(c for c in charts if c["id"] == "roic")


def test_roic_chart_draws_the_required_return(client):
    from pricedin.data import treasury

    year = date.today().year
    csv = f'Date,"10 Yr"\n10/08/{year},5.22\n'.encode()
    archive.store(treasury.yield_curve_kind(year), "fixture", csv)
    chart = roic_chart(client)
    assert chart["reference"]["value"] == pytest.approx(0.1022)
    assert chart["reference"]["label"] == "required return 10.2%"
    assert f"10-year Treasury yield (5.22% on {year}-10-08) plus a 5% equity" in chart["note"]


def test_roic_chart_without_a_yield_says_how_to_get_one(client):
    chart = roic_chart(client)
    assert chart["reference"] is None
    assert "Refresh to fetch the 10-year Treasury yield" in chart["note"]
