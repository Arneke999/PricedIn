"""EDGAR responses -> canonical schema."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from pricedin.normalize.restated import annual, filing_key
from pricedin.normalize.schema import Conflict, Fact, Period, Statements
from pricedin.normalize.tags import CHAINS


def ticker_index(body: bytes) -> dict[str, tuple[int, str]]:
    """company_tickers.json -> {TICKER: (cik, company name)}."""
    rows = json.loads(body).values()
    return {row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in rows}


def _fact(concept: str, period: Period, tag: str, entry: dict) -> Fact:
    return Fact(
        concept=concept,
        period=period,
        value=float(entry["val"]),
        unit="USD",
        source_tag=tag,
        accession=entry["accn"],
        form=entry["form"],
        filed=date.fromisoformat(entry["filed"]),
    )


def statements(body: bytes) -> Statements:
    """For each concept and period: the newest filing wins, then the tag chain order
    decides within that filing. Chain tags in the same filing that disagree are conflicts."""
    data = json.loads(body)
    gaap = data.get("facts", {}).get("us-gaap", {})
    facts: dict[str, dict[Period, Fact]] = {}
    conflicts: list[Conflict] = []
    for concept, chain in CHAINS.items():
        candidates: dict[Period, list[tuple[int, str, dict]]] = defaultdict(list)
        for rank, tag in enumerate(chain):
            usd = gaap.get(tag, {}).get("units", {}).get("USD", [])
            for period, entry in annual(usd):
                candidates[period].append((rank, tag, entry))

        resolved: dict[Period, Fact] = {}
        for period, found in candidates.items():
            newest = max(filing_key(entry) for _, _, entry in found)
            in_filing = sorted((c for c in found if filing_key(c[2]) == newest), key=lambda c: c[0])
            _, tag, entry = in_filing[0]
            resolved[period] = chosen = _fact(concept, period, tag, entry)
            for _, other_tag, other in in_filing[1:]:
                if other_tag != tag and float(other["val"]) != chosen.value:
                    conflicts.append(
                        Conflict(concept, period, chosen, _fact(concept, period, other_tag, other))
                    )
        facts[concept] = dict(sorted(resolved.items()))
    return Statements(
        cik=int(data["cik"]), name=data["entityName"], facts=facts, conflicts=conflicts
    )
