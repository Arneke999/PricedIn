import io
from datetime import date

import pytest

from pricedin.data import archive, treasury
from pricedin.metrics.discount import required_return
from pricedin.normalize.treasury import latest_ten_year

CSV = (
    '﻿Date,"1 Mo","5 Yr","10 Yr","30 Yr"\n'
    "10/08/2026,4.14,4.99,5.22,5.60\n"
    "10/09/2026,4.10,4.95,,5.58\n"  # a day without a 10-year value
    "10/07/2026,4.07,5.03,5.28,5.67\n"
).encode()


def test_latest_ten_year_is_the_newest_date_with_a_value():
    assert latest_ten_year(CSV) == (date(2026, 10, 8), pytest.approx(0.0522))


def test_no_ten_year_values_means_none():
    assert latest_ten_year(b'Date,"10 Yr"\n10/08/2026,\n') is None


def test_required_return_adds_the_premium():
    assert required_return(0.0522) == pytest.approx(0.1022)


def test_fetch_archives_the_raw_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEDIN_RAW_DIR", str(tmp_path))
    monkeypatch.setattr(treasury.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(CSV))
    entry = treasury.fetch_year(2026)
    body, stored = archive.latest(treasury.yield_curve_kind(2026))
    assert body == CSV
    assert "field_tdr_date_value=2026" in stored["url"] == entry["url"]
