"""Predecessor CIKs: companies whose history sits under an older CIK (DECISIONS #35).

No structured SEC field links a successor to its predecessor, so the map is manual. Policy:
stitch only holding-company reorganizations and redomiciliations, where the consolidated
entity is the same before and after. Never mergers or spin-offs, even when they come with
an 8-K12B. Adding an entry is Arne's decision; `successor_signals` only flags candidates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from pricedin.data import archive
from pricedin.data.edgar import TICKERS_KIND
from pricedin.normalize.edgar import ticker_index


@dataclass(frozen=True)
class Predecessor:
    cik: int
    name: str
    effective: date
    accession: str  # the successor's 8-K12B announcing the succession
    note: str


# Successor CIK -> its predecessors. Evidence in docs/spike/history.md.
PREDECESSORS: dict[int, tuple[Predecessor, ...]] = {
    2115436: (
        Predecessor(
            cik=34088,
            name="Exxon Mobil Corp",
            effective=date(2026, 7, 1),
            accession="0001193125-26-291990",
            note="Redomiciliation from New Jersey to Texas; shares exchanged 1:1.",
        ),
    ),
    1652044: (
        Predecessor(
            cik=1288776,
            name="Google Inc.",
            effective=date(2015, 10, 2),
            accession="0001193125-15-336577",
            note="Holding-company reorganization; Google Inc. became a subsidiary of Alphabet.",
        ),
    ),
}

SUCCESSION_FORMS = {"8-K12B", "8-K12B/A", "8-K12G3", "8-K12G3/A"}


def _ticker_moves(ticker: str, cik: int) -> list[str]:
    """Archived ticker snapshots in which the ticker pointed to a different CIK."""
    first_seen: dict[int, tuple[str, str]] = {}  # other CIK -> (name, fetch date)
    parsed: dict[str, dict[str, tuple[int, str]]] = {}  # identical snapshots parse once
    for entry in archive.entries(TICKERS_KIND):
        sha = entry["sha256"]
        if sha not in parsed:
            parsed[sha] = ticker_index(archive.body(TICKERS_KIND, entry))
        other = parsed[sha].get(ticker.upper())
        if other and other[0] != cik and other[0] not in first_seen:
            first_seen[other[0]] = (other[1], entry["fetched_at"][:10])
    return [
        f"{ticker.upper()} pointed to CIK {other} ({name}) in the ticker list fetched "
        f"{fetched}, so history may sit under that CIK."
        for other, (name, fetched) in first_seen.items()
    ]


def _succession_filings(submissions_body: bytes) -> list[tuple[str, str, str]]:
    """(form, filing date, accession) for each 8-K12B/8-K12G3 in the recent filings.
    Older pages aren't fetched, but a successor with little history files them recently."""
    recent = json.loads(submissions_body).get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        strict=True,
    )
    return [row for row in rows if row[0] in SUCCESSION_FORMS]


def successor_signals(
    ticker: str, cik: int, submissions_body: bytes, resolved_years: int
) -> list[str]:
    """Reasons this CIK may have a predecessor that isn't in PREDECESSORS yet."""
    if cik in PREDECESSORS:
        return []
    signals = _ticker_moves(ticker, cik)
    if resolved_years < 3:
        signals += [
            f"CIK {cik} has {resolved_years} year(s) of history and filed Form {form} on {filed} "
            f"({accession}), the form a successor files after a reorganization, so an "
            "earlier CIK may hold the rest."
            for form, filed, accession in _succession_filings(submissions_body)
        ]
    return signals
