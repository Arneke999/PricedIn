"""EDGAR responses -> canonical schema."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from pricedin.normalize.restated import SAME_START, annual, filing_key, in_window, nominal_year
from pricedin.normalize.schema import (
    Break,
    Conflict,
    Fact,
    Flag,
    Period,
    Stale,
    Statements,
    pct_change,
)
from pricedin.normalize.tags import (
    CAPEX_PPE,
    CAPEX_SOFTWARE,
    CHAINS,
    CONTRACT_REVENUE,
    HINTS,
    NON_CONTRACT_REVENUE,
)

# Recast breaks smaller than this are rounding, not a change of basis (golden tolerance).
BREAK_THRESHOLD = 0.005


def ticker_index(body: bytes) -> dict[str, tuple[int, str]]:
    """company_tickers.json -> {TICKER: (cik, company name)}."""
    rows = json.loads(body).values()
    return {row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in rows}


@dataclass
class _Filing:
    filed: str
    accn: str
    own_end: date
    fy: int | None


@dataclass(frozen=True)
class _Source:
    cik: int
    gaap: dict


@dataclass(frozen=True)
class _Candidate:
    rank: int
    tag: str
    period: Period
    entry: dict
    cik: int

    def fact(self, concept: str) -> Fact:
        return Fact(
            concept=concept,
            period=self.period,
            value=float(self.entry["val"]),
            unit="USD",
            source_tag=self.tag,
            accession=self.entry["accn"],
            form=self.entry["form"],
            filed=date.fromisoformat(self.entry["filed"]),
            cik=self.cik,
        )


def _usd_annual(source: _Source, tag: str):
    return annual(source.gaap.get(tag, {}).get("units", {}).get("USD", []))


def _index(sources: Sequence[_Source]) -> dict[str, _Filing]:
    """Every annual filing and the fiscal year it's about."""
    filings: dict[str, _Filing] = {}
    for source in sources:
        for concept in source.gaap.values():
            for entries in concept.get("units", {}).values():
                for period, entry in annual(entries):
                    accn = entry["accn"]
                    f = filings.get(accn)
                    if f is None:
                        f = filings[accn] = _Filing(
                            entry["filed"], accn, period.end, entry.get("fy")
                        )
                    elif period.end > f.own_end:
                        f.own_end = period.end
                    if f.fy is None:
                        f.fy = entry.get("fy")
    return filings


def _software(sources: Sequence[_Source]) -> dict[tuple[str, date], tuple[str, dict]]:
    """(accession, year end) -> the capitalized-software tag and entry it reports."""
    found: dict[tuple[str, date], tuple[str, dict]] = {}
    for tag in CAPEX_SOFTWARE:
        for source in sources:
            for period, entry in _usd_annual(source, tag):
                found.setdefault((entry["accn"], period.end), (tag, entry))
    return found


def _filing_fact(concept: str, ranked: list[_Candidate], software: dict) -> Fact:
    """A filing's value for a concept and year: its first chain tag, plus capitalized
    software on top of PP&E capex (DECISIONS #41)."""
    first = ranked[0]
    fact = first.fact(concept)
    if concept == "capex" and first.tag == CAPEX_PPE:
        extra = software.get((first.entry["accn"], first.period.end))
        if extra:
            tag, entry = extra
            fact = replace(
                fact, value=fact.value + float(entry["val"]), source_tag=f"{first.tag} + {tag}"
            )
    return fact


def _hints(sources: Sequence[_Source], concept: str, accn: str, end: date) -> tuple:
    """Tags in a filing, for a year, whose names look like the concept."""
    found = []
    for source in sources:
        for tag in source.gaap:
            if tag in CHAINS[concept] or not any(h in tag for h in HINTS[concept]):
                continue
            for period, entry in _usd_annual(source, tag):
                if entry["accn"] == accn and period.end == end:
                    found.append((tag, float(entry["val"])))
                    break
    return tuple(found[:5])


def _fy_offset(primary: _Source, filings: dict[str, _Filing]) -> int:
    """How the company names its fiscal year, from its latest 10-K (DECISIONS #29)."""
    own = {e["accn"] for c in primary.gaap.values() for u in c.get("units", {}).values() for e in u}
    latest = max(
        (f for a, f in filings.items() if a in own), key=lambda f: (f.filed, f.accn), default=None
    )
    if latest is None or latest.fy is None:
        return 0
    return int(latest.fy) - nominal_year(latest.own_end)


def statements(body: bytes, predecessors: Sequence[bytes] = ()) -> Statements:
    """Resolve the canonical annual line items.

    For each concept and fiscal year (keyed by end date): the newest filing that reports a
    chain tag for that year wins, then the chain order decides within that filing. A
    filing's value counts only for its own last three fiscal years. `predecessors` are
    companyfacts bodies of predecessor CIKs (DECISIONS #35), pooled with the primary.
    """
    docs = [json.loads(b) for b in (body, *predecessors)]
    sources = [_Source(int(d["cik"]), d.get("facts", {}).get("us-gaap", {})) for d in docs]
    filings = _index(sources)

    result = Statements(
        cik=sources[0].cik,
        name=docs[0].get("entityName", ""),
        facts={},
        fy_offset=_fy_offset(sources[0], filings),
        taxonomies={name: len(c) for name, c in docs[0].get("facts", {}).items()},
    )
    by_concept: dict[str, dict[date, list[_Candidate]]] = {}
    # Years each filing presents in its statements: any chain tag of any concept. A note
    # that merely mentions an older year (2-year smaller-company statements) doesn't count.
    presented: dict[str, set[date]] = defaultdict(set)
    for concept, chain in CHAINS.items():
        candidates = by_concept[concept] = defaultdict(list)
        for rank, tag in enumerate(chain):
            for source in sources:
                for period, entry in _usd_annual(source, tag):
                    if in_window(period.end, filings[entry["accn"]].own_end):
                        candidates[period.end].append(
                            _Candidate(rank, tag, period, entry, source.cik)
                        )
                        presented[entry["accn"]].add(period.end)

    software = _software(sources)
    for concept, candidates in by_concept.items():
        resolved: dict[date, Fact] = {}
        for end in sorted(candidates):
            found = candidates[end]
            newest = max(filing_key(c.entry) for c in found)
            in_filing = sorted(
                (c for c in found if filing_key(c.entry) == newest), key=lambda c: c.rank
            )
            winner = in_filing[0]
            chosen = resolved[end] = _filing_fact(concept, in_filing, software)

            for other in in_filing[1:]:
                same_year = abs(other.period.start - winner.period.start) <= SAME_START
                if (
                    same_year
                    and other.tag != winner.tag
                    and other.fact(concept).value != chosen.value
                ):
                    result.conflicts.append(Conflict(concept, end, chosen, other.fact(concept)))

            newer = [
                f
                for f in filings.values()
                if (f.filed, f.accn) > newest and end in presented[f.accn]
            ]
            if newer:
                latest = max(newer, key=lambda f: (f.filed, f.accn))
                hints = _hints(sources, concept, latest.accn, end)
                stale = Stale(
                    concept, end, chosen, latest.accn, date.fromisoformat(latest.filed), hints
                )
                result.stale.append(stale)

            if winner.tag in CONTRACT_REVENUE:
                for source in sources:
                    for period, entry in _usd_annual(source, NON_CONTRACT_REVENUE):
                        if entry["accn"] == chosen.accession and period.end == end:
                            result.flags.append(
                                Flag(
                                    concept,
                                    end,
                                    "Revenue is contract revenue (ASC 606); the same filing also "
                                    "reports revenue outside customer contracts, so the total "
                                    "may be higher.",
                                )
                            )
                            break

        ends = sorted(resolved)
        for prev_end, end in zip(ends, ends[1:], strict=False):
            older = resolved[prev_end].accession
            if older == resolved[end].accession:
                continue
            restated = sorted(
                (c for c in candidates[end] if c.entry["accn"] == older), key=lambda c: c.rank
            )
            if not restated:
                continue
            before = _filing_fact(concept, restated, software)
            change = pct_change(before.value, resolved[end].value)
            if change is not None and abs(change) > BREAK_THRESHOLD:
                result.breaks.append(Break(concept, end, prev_end, before, resolved[end]))

        result.facts[concept] = resolved
    return result
