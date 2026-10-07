"""EDGAR responses -> canonical schema."""

from __future__ import annotations

import json
from datetime import date

from pricedin.normalize.restated import latest_annual
from pricedin.normalize.schema import Conflict, Fact, Period, Statements
from pricedin.normalize.tags import CHAINS


def ticker_index(body: bytes) -> dict[str, tuple[int, str]]:
    """company_tickers.json -> {TICKER: (cik, company name)}."""
    rows = json.loads(body).values()
    return {row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in rows}


def statements(body: bytes) -> Statements:
    data = json.loads(body)
    gaap = data.get("facts", {}).get("us-gaap", {})
    facts: dict[str, dict[Period, Fact]] = {}
    conflicts: list[Conflict] = []
    for concept, chain in CHAINS.items():
        resolved: dict[Period, Fact] = {}
        for tag in chain:
            usd = gaap.get(tag, {}).get("units", {}).get("USD", [])
            for period, entry in latest_annual(usd).items():
                fact = Fact(
                    concept=concept,
                    period=period,
                    value=float(entry["val"]),
                    unit="USD",
                    source_tag=tag,
                    accession=entry["accn"],
                    form=entry["form"],
                    filed=date.fromisoformat(entry["filed"]),
                )
                chosen = resolved.get(period)
                if chosen is None:
                    resolved[period] = fact
                elif chosen.value != fact.value:
                    conflicts.append(Conflict(concept, period, chosen, fact))
        facts[concept] = dict(sorted(resolved.items()))
    return Statements(
        cik=int(data["cik"]), name=data["entityName"], facts=facts, conflicts=conflicts
    )
