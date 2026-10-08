"""Pages chart only verified series (display gate, DECISIONS #17, #42)."""

import json
import re
from pathlib import Path

import pytest

from pricedin.data import archive, edgar
from pricedin.metrics.verified import VERIFIED
from pricedin.web.app import COMPANY_CHARTS, app

KO_FIXTURE = Path(__file__).parent / "golden" / "fixtures" / "KO.json"
KO_CIK = 21344


@pytest.fixture
def client(tmp_path, monkeypatch):
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


def test_coverage_page_names_line_items_without_a_golden_test(client):
    html = client.get("/company/KO/coverage").get_data(as_text=True)
    note = re.search(r"No golden test yet for:\s+([^.]+)\.", html)
    assert note is not None
    assert note.group(1) == "net income"
