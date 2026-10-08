"""Write trimmed companyfacts snapshots for the golden tests.

Run: uv run python -m tests.golden.make_fixtures

Golden values are pinned to the 10-Ks they were read from, so the tests run against a fixed
snapshot rather than whatever was fetched last. Each fixture keeps only the tags the
resolver can use, from the archived response named in its header. SEC data is public, so
committing it is fine (Hard rule 6). Regenerate when a chain gains a tag; refreshing to a
newer snapshot can change "latest restated" values, which then need Arne's recheck.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pricedin.data import archive, edgar
from pricedin.normalize.tags import CAPEX_SOFTWARE, CHAINS, NON_CONTRACT_REVENUE

HERE = Path(__file__).parent


def fixture_tags() -> list[str]:
    return sorted(
        {t for chain in CHAINS.values() for t in chain} | {NON_CONTRACT_REVENUE, *CAPEX_SOFTWARE}
    )


def main() -> None:
    golden = tomllib.loads((HERE / "values.toml").read_text())
    tags = fixture_tags()
    (HERE / "fixtures").mkdir(exist_ok=True)
    for ticker, company in golden.items():
        kind = edgar.companyfacts_kind(company["cik"])
        cached = archive.latest(kind)
        if cached is None:
            raise SystemExit(f"{ticker}: no archived companyfacts; fetch it in the app first")
        body, entry = cached
        data = json.loads(body)
        gaap = data["facts"].get("us-gaap", {})
        fixture = {
            "pricedin_fixture": {
                "source": entry["url"],
                "sha256": entry["sha256"],
                "fetched_at": entry["fetched_at"],
                "tags": tags,
            },
            "cik": data["cik"],
            "entityName": data["entityName"],
            "facts": {"us-gaap": {t: gaap[t] for t in tags if t in gaap}},
        }
        path = HERE / "fixtures" / f"{ticker}.json"
        path.write_text(json.dumps(fixture, separators=(",", ":"), sort_keys=True) + "\n")
        print(f"{ticker}: {path.stat().st_size / 1e3:.0f} kB from {entry['sha256'][:12]}")


if __name__ == "__main__":
    main()
