"""Write trimmed companyfacts snapshots for the golden tests.

Run: uv run python -m tests.golden.make_fixtures

Golden values are pinned to the 10-Ks they were read from, so the tests run against a fixed
snapshot rather than whatever was fetched last. Each fixture keeps only the tags the
resolver can use, from the archived response named in its header. SEC data is public, so
committing it is fine (Hard rule 6). Regenerate when a chain gains a tag: an existing
fixture is rebuilt from the snapshot it pins (its sha256), so a later refresh can't shift
values Arne verified. To move a company to a newer snapshot, delete its fixture first; new
"latest restated" values then need Arne's recheck.
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


def pinned(kind: str, path: Path) -> tuple[bytes, dict]:
    meta = json.loads(path.read_text())["pricedin_fixture"]
    same = [e for e in archive.entries(kind) if e["sha256"] == meta["sha256"]]
    entry = next((e for e in same if e["fetched_at"] == meta["fetched_at"]), None) or (
        same[0] if same else None
    )
    sha = meta["sha256"]
    if entry is None:
        raise SystemExit(f"{path.name}: pinned snapshot {sha[:12]} is not in the archive")
    return archive.body(kind, entry), entry


def latest(kind: str, ticker: str) -> tuple[bytes, dict]:
    cached = archive.latest(kind)
    if cached is None:
        raise SystemExit(f"{ticker}: no archived companyfacts; fetch it in the app first")
    return cached


def main() -> None:
    golden = tomllib.loads((HERE / "values.toml").read_text())
    tags = fixture_tags()
    (HERE / "fixtures").mkdir(exist_ok=True)
    for ticker, company in golden.items():
        kind = edgar.companyfacts_kind(company["cik"])
        path = HERE / "fixtures" / f"{ticker}.json"
        body, entry = pinned(kind, path) if path.exists() else latest(kind, ticker)
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
        path.write_text(json.dumps(fixture, separators=(",", ":"), sort_keys=True) + "\n")
        print(f"{ticker}: {path.stat().st_size / 1e3:.0f} kB from {entry['sha256'][:12]}")


if __name__ == "__main__":
    main()
