"""SEC EDGAR fetchers. Fetch and archive raw bytes, nothing else."""

from __future__ import annotations

import time
import urllib.request

from pricedin import config
from pricedin.data import archive

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

TICKERS_KIND = "sec/company_tickers"

# SEC fair access allows 10 requests/s per user. Stay well under it.
_MIN_INTERVAL = 0.15
_last_request = 0.0


def companyfacts_kind(cik: int) -> str:
    return f"sec/companyfacts/CIK{cik:010d}"


def _get(url: str) -> bytes:
    global _last_request
    user_agent = config.sec_user_agent()
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    finally:
        _last_request = time.monotonic()


def fetch_tickers() -> dict:
    body = _get(TICKERS_URL)
    return archive.store(TICKERS_KIND, TICKERS_URL, body)


def fetch_companyfacts(cik: int) -> dict:
    url = COMPANYFACTS_URL.format(cik=cik)
    body = _get(url)
    return archive.store(companyfacts_kind(cik), url, body)
