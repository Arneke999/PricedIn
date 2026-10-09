"""Treasury.gov daily par yield curve (10-year yield for the required return, DECISIONS #69).

No key and no personal User-Agent needed. Fetch and archive raw bytes, nothing else; SEC and
Treasury responses are archived immutably (Hard rule 4).
"""

from __future__ import annotations

import ssl
import urllib.request

from pricedin import config
from pricedin.data import archive

URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&_format=csv"
)
USER_AGENT = "PricedIn (self-hosted stock research tool)"


def yield_curve_kind(year: int) -> str:
    return f"treasury/yield_curve/{year}"


def fetch_year(year: int) -> dict:
    """One calendar year of daily par yields, newest first."""
    url = URL.format(year=year)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    cafile = config.get("SSL_CERT_FILE")
    context = ssl.create_default_context(cafile=cafile) if cafile else None
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        body = response.read()
    return archive.store(yield_curve_kind(year), url, body)
