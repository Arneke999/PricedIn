import json

import pytest

from pricedin.data import archive
from pricedin.data.edgar import TICKERS_KIND
from pricedin.normalize import predecessors


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEDIN_RAW_DIR", str(tmp_path))


def tickers(**ciks: int) -> bytes:
    rows = [{"cik_str": cik, "ticker": t, "title": f"{t} Co"} for t, cik in ciks.items()]
    return json.dumps(dict(enumerate(rows))).encode()


def submissions(filings=()) -> bytes:
    """filings: (form, filing date, accession) triples."""
    recent = {
        "form": [f for f, _, _ in filings],
        "filingDate": [d for _, d, _ in filings],
        "accessionNumber": [a for _, _, a in filings],
    }
    return json.dumps({"cik": "222", "filings": {"recent": recent}}).encode()


SUCCESSION = [("8-K12B", "2026-07-01", "0000000000-26-000001"), ("10-Q", "2026-08-01", "x")]


def test_ticker_that_moved_cik_is_flagged():
    archive.store(TICKERS_KIND, "https://example.test/t", tickers(ABC=111))
    archive.store(TICKERS_KIND, "https://example.test/t", tickers(ABC=222))
    signals = predecessors.successor_signals("abc", 222, submissions(), resolved_years=10)
    assert len(signals) == 1
    assert "CIK 111" in signals[0]


def test_ticker_that_never_moved_is_not_flagged():
    archive.store(TICKERS_KIND, "https://example.test/t", tickers(ABC=222, XYZ=111))
    assert predecessors.successor_signals("ABC", 222, submissions(), resolved_years=10) == []


def test_8k12b_with_short_history_is_flagged():
    signals = predecessors.successor_signals("ABC", 222, submissions(SUCCESSION), 1)
    assert len(signals) == 1
    assert "8-K12B" in signals[0]


def test_8k12b_with_long_history_is_not_flagged():
    assert predecessors.successor_signals("ABC", 222, submissions(SUCCESSION), 3) == []


def test_mapped_successor_has_no_signals():
    archive.store(TICKERS_KIND, "https://example.test/t", tickers(XOM=34088))
    archive.store(TICKERS_KIND, "https://example.test/t", tickers(XOM=2115436))
    assert predecessors.successor_signals("XOM", 2115436, submissions(SUCCESSION), 0) == []


def test_no_successor_is_its_own_predecessor():
    for successor, preds in predecessors.PREDECESSORS.items():
        assert successor not in {p.cik for p in preds}
