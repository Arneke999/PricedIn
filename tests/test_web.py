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
from pricedin.normalize.schema import Fact, Period, Stale, Statements
from pricedin.web.app import COMPANY_CHARTS, _warnings, app

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
        assert [(p["end"], p["value"]) for p in chart["points"]] == [
            (end.isoformat(), value) for end, value in values.items()
        ]


def test_coverage_page_names_line_items_without_a_golden_test(client):
    html = client.get("/company/KO/coverage").get_data(as_text=True)
    note = re.search(r"No golden test yet for:\s+([^.]+)\.", html)
    assert note is not None
    assert note.group(1) == "net income"


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
