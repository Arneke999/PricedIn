"""EDGAR responses -> canonical schema."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction

from pricedin.normalize import tags as t
from pricedin.normalize.restated import (
    SAME_START,
    annual,
    filing_key,
    in_window,
    nominal_year,
    year_ends,
)
from pricedin.normalize.schema import (
    Break,
    Conflict,
    Fact,
    Flag,
    Period,
    Split,
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
    INSTANTS,
    NARROWER,
    NON_CONTRACT_REVENUE,
    SUMMED,
    UNITS,
)

# Recast breaks smaller than this are rounding, not a change of basis (golden tolerance).
BREAK_THRESHOLD = 0.005
# Stock-split ratios recognised (reverse splits are their inverses). Any other ratio,
# including 1000x scaling errors in the tagging, stays a break.
SPLIT_RATIOS = tuple(
    Fraction(n) for n in (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100)
) + (Fraction(3, 2), Fraction(4, 3), Fraction(5, 4), Fraction(5, 2))


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
            unit=_unit(concept),
            source_tag=self.tag,
            accession=self.entry["accn"],
            form=self.entry["form"],
            filed=date.fromisoformat(self.entry["filed"]),
            cik=self.cik,
        )


def _unit(concept: str) -> str:
    return UNITS.get(concept, "USD")


def _annual(source: _Source, tag: str, unit: str = "USD"):
    return annual(source.gaap.get(tag, {}).get("units", {}).get(unit, []))


def _reported(source: _Source, tag: str, concept: str, fiscal_ends: set[date]):
    """A tag's annual values (or year-end balances) in the concept's unit."""
    entries = source.gaap.get(tag, {}).get("units", {}).get(_unit(concept), [])
    if concept in INSTANTS:
        return year_ends(entries, fiscal_ends)
    return annual(entries)


def _index(sources: Sequence[_Source]) -> tuple[dict[str, _Filing], set[date]]:
    """Every annual filing and the fiscal year it's about, and every fiscal-year end."""
    filings: dict[str, _Filing] = {}
    fiscal_ends: set[date] = set()
    for source in sources:
        for concept in source.gaap.values():
            for entries in concept.get("units", {}).values():
                for period, entry in annual(entries):
                    fiscal_ends.add(period.end)
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
    return filings, fiscal_ends


def _software(sources: Sequence[_Source]) -> dict[tuple[str, date], tuple[str, dict]]:
    """(accession, year end) -> the capitalized-software tag and entry it reports."""
    found: dict[tuple[str, date], tuple[str, dict]] = {}
    for tag in CAPEX_SOFTWARE:
        for source in sources:
            for period, entry in _annual(source, tag):
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


def _money(value: float) -> str:
    return f"${value / 1e9:,.1f}B" if abs(value) >= 1e9 else f"${value / 1e6:,.0f}M"


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= BREAK_THRESHOLD * max(abs(a), abs(b))


def _first(found: dict[str, float], tags: Sequence[str]) -> str | None:
    return next((tag for tag in tags if tag in found), None)


def _includes_leases(found: dict[str, float], used: str | None, pair: Sequence[str]) -> bool:
    """Does the debt tag used already contain finance leases? Yes when it says so, or when
    the filing reports the lease-inclusive variant at the same value."""
    if used in t.INCLUDES_LEASES:
        return True
    other = next((tag for tag in pair if tag in t.INCLUDES_LEASES), None)
    return used is not None and other in found and _close(found[used], found[other])


def _debt(found: dict[str, float]) -> tuple[list[str], list[str]]:
    """Debt from one filing's tags at one year-end: the tags summed, and any problems
    (DECISIONS #60)."""
    current = _first(found, t.CURRENT_LONG_TERM_DEBT)
    parts = [tag for tag in t.SHORT_TERM_BORROWING_PARTS if tag in found]
    readings = [parts]
    if t.SHORT_TERM_BORROWINGS in found:
        # Usually the total of the parts; at some filers it excludes commercial paper (NEE).
        readings = [[t.SHORT_TERM_BORROWINGS], [t.SHORT_TERM_BORROWINGS, *parts]]
    short = readings[0]
    if t.DEBT_CURRENT in found and len(readings) > 1 and parts:
        current_part = found[current] if current else 0.0
        short = next(
            (
                r
                for r in readings
                if _close(found[t.DEBT_CURRENT], sum(found[tag] for tag in r) + current_part)
            ),
            short,
        )
    noncurrent = _first(found, t.NONCURRENT_LONG_TERM_DEBT)
    whole_current = not short and current is None and t.DEBT_CURRENT in found
    if whole_current:
        short = [t.DEBT_CURRENT]
    current_leases_inside = whole_current or _includes_leases(
        found, current, t.CURRENT_LONG_TERM_DEBT
    )
    noncurrent_leases_inside = _includes_leases(found, noncurrent, t.NONCURRENT_LONG_TERM_DEBT)
    debt = short + [tag for tag in (current, noncurrent) if tag]
    problems = []

    leases = []
    lease_current = _first(found, t.FINANCE_LEASES_CURRENT)
    lease_noncurrent = _first(found, t.FINANCE_LEASES_NONCURRENT)
    lease_total = _first(found, t.FINANCE_LEASES_TOTAL)
    if lease_current or lease_noncurrent:
        if lease_current and not current_leases_inside:
            leases.append(lease_current)
        if lease_noncurrent and not noncurrent_leases_inside:
            leases.append(lease_noncurrent)
    elif lease_total and not (current_leases_inside and noncurrent_leases_inside):
        if current_leases_inside or noncurrent_leases_inside:
            problems.append(
                f"Finance leases ({_money(found[lease_total])}) are reported only as a total, "
                "and part of them may already be inside the debt lines, so they aren't added."
            )
        else:
            leases.append(lease_total)

    if found.get(t.DISPOSAL_GROUP_LIABILITIES):
        problems.append(
            "Part of the business is held for sale or discontinued: its debt and cash sit "
            "outside the lines PricedIn reads. If its profit is still in operating income, "
            "invested capital is understated this year."
        )
    if not debt and t.DEBT_TOTAL in found:
        debt = [t.DEBT_TOTAL]
    total = sum(found[tag] for tag in debt)
    with_leases = total + sum(found[tag] for tag in leases)
    long_term = sum(found[tag] for tag in (current, noncurrent) if tag)
    checks = [
        (t.DEBT_TOTAL, (total, with_leases)),
        (t.LONG_TERM_DEBT_TOTAL, (long_term, long_term + with_leases - total)),
    ]
    if not whole_current:
        short_and_current = sum(found[tag] for tag in short) + (found[current] if current else 0)
        lease_part = found[lease_current] if lease_current in leases else 0
        checks.append((t.DEBT_CURRENT, (short_and_current, short_and_current + lease_part)))
    for tag, sums in checks:
        if tag in found and tag not in debt and not any(_close(found[tag], s) for s in sums):
            problems.append(
                f"The 10-K's own total {tag} is {_money(found[tag])}, but the debt lines "
                f"PricedIn adds come to {_money(sums[0])}; debt may be miscounted this year."
            )
    return debt + leases, problems


def _cash(found: dict[str, float]) -> tuple[list[str], list[str]]:
    """Cash and short-term investments from one filing's tags at one year-end: the tags
    summed, and any problems (DECISIONS #61)."""
    cash = _first(found, t.CASH)
    investments = _first(found, t.SHORT_TERM_INVESTMENTS)
    parts = [tag for tag in (cash, investments, t.OTHER_SHORT_TERM_INVESTMENTS) if tag in found]
    problems = []
    if t.MARKETABLE_SECURITIES in found:
        if any(tag in found for tag in t.MARKETABLE_SPLIT):
            problems.append(
                f"{t.MARKETABLE_SECURITIES} ({_money(found[t.MARKETABLE_SECURITIES])}) isn't "
                "counted: the filing also splits marketable securities into current and "
                "long-term, so it may include long-term ones."
            )
        else:
            parts.append(t.MARKETABLE_SECURITIES)
    if t.INVESTMENTS in found:
        current = found.get(t.ASSETS_CURRENT)
        if (
            current is not None
            and not any(tag in found for tag in t.INVESTMENT_SPLITS)
            and sum(found[tag] for tag in parts) + found[t.INVESTMENTS] <= current
        ):
            parts.append(t.INVESTMENTS)
        else:
            problems.append(
                f"{t.INVESTMENTS} ({_money(found[t.INVESTMENTS])}) isn't counted: the filing "
                "doesn't show it's a short-term line."
            )

    total = found.get(t.CASH_AND_INVESTMENTS_TOTAL)
    if total is None:
        for tag in t.SHORT_TERM_INVESTMENTS:
            if tag in found and tag != investments and not _close(found[tag], found[investments]):
                problems.append(
                    f"{tag} ({_money(found[tag])}) isn't counted; only {investments} is."
                )
        return parts, problems
    separate = [tag for tag in parts if tag in t.MARKETABLE_LINES]
    if _close(total, sum(found[tag] for tag in parts)) or (cash and _close(total, found[cash])):
        # The parts add up, or short-term investments sit inside cash equivalents (TGT)
        return [t.CASH_AND_INVESTMENTS_TOTAL], problems
    inside = sum(found[tag] for tag in parts if tag not in separate)
    if separate and _close(total, inside):
        return [t.CASH_AND_INVESTMENTS_TOTAL, *separate], problems
    problems.append(
        f"The 10-K's cash and short-term investments total ({_money(total)}) doesn't match "
        f"its parts ({_money(sum(found[tag] for tag in parts))}); PricedIn uses the total."
    )
    return [t.CASH_AND_INVESTMENTS_TOTAL], problems


def _equity(found: dict[str, float]) -> tuple[list[str], list[str]]:
    """Equity including minority holders, plus redeemable NCI outside equity (#59, #65)."""
    base = _first(found, t.EQUITY)
    if base is None:
        return [], []
    redeemable = _first(found, t.REDEEMABLE_NCI)
    return [base, redeemable] if redeemable else [base], []


def _summed(concept: str, ranked: list[_Candidate]) -> tuple[Fact | None, list[str]]:
    """A summed concept from one filing's tags at one year-end, and any problems."""
    found: dict[str, float] = {}
    for c in ranked:
        found.setdefault(c.tag, float(c.entry["val"]))
    used, problems = {"equity": _equity, "debt": _debt}.get(concept, _cash)(found)
    if not used:
        return None, problems
    fact = replace(
        ranked[0].fact(concept),
        value=sum(found[tag] for tag in used),
        source_tag=" + ".join(used),
    )
    return fact, problems


def _resolve(
    concept: str, ranked: list[_Candidate], software: dict, factors: dict[str, float]
) -> tuple[Fact | None, list[str]]:
    """A filing's value for a concept and year, and any problems found summing it."""
    if concept in SUMMED:
        return _summed(concept, ranked)
    return _adjusted(_filing_fact(concept, ranked, software), factors), []


def _hints(
    sources: Sequence[_Source], concept: str, accn: str, end: date, fiscal_ends: set[date]
) -> tuple:
    """Tags in a filing, for a year, whose names look like the concept."""
    found = []
    for source in sources:
        for tag in source.gaap:
            if tag in CHAINS[concept] or not any(h in tag for h in HINTS[concept]):
                continue
            for period, entry in _reported(source, tag, concept, fiscal_ends):
                if entry["accn"] == accn and period.end == end:
                    found.append((tag, float(entry["val"])))
                    break
    return tuple(found[:5])


def _split_ratio(before: float, after: float) -> float | None:
    """after / before when it is a stock-split ratio (4:1, 3:2, 1:8, ...), else None."""
    if before <= 0 or after <= 0:
        return None
    ratio = after / before
    up = ratio if ratio >= 1 else 1 / ratio
    for clean in SPLIT_RATIOS:
        if abs(up / clean - 1) <= BREAK_THRESHOLD:
            return float(clean if ratio >= 1 else 1 / clean)
    return None


def _split_factors(
    concept: str, candidates: dict[date, list[_Candidate]]
) -> tuple[dict[str, float], list[Split]]:
    """Per filing, the factor that puts its share counts on the newest filing's basis
    (DECISIONS #50).

    Each filing is compared with the nearest newer filing that reports one of the same
    years; a split ratio between their values for that year is a stock split. A filing
    that shares no year with a newer one keeps the next newer filing's basis.
    """
    by_filing: dict[str, dict[date, _Candidate]] = defaultdict(dict)
    for end, found in candidates.items():
        for c in sorted(found, key=lambda c: c.rank):
            by_filing[c.entry["accn"]].setdefault(end, c)
    order = sorted(
        by_filing, key=lambda a: filing_key(next(iter(by_filing[a].values())).entry), reverse=True
    )
    factors: dict[str, float] = {}
    splits: list[Split] = []
    for i, accn in enumerate(order):
        factor = factors[order[i - 1]] if i else 1.0
        for newer in reversed(order[:i]):
            shared = by_filing[accn].keys() & by_filing[newer].keys()
            if not shared:
                continue
            end = max(shared)
            old, new = by_filing[accn][end], by_filing[newer][end]
            ratio = _split_ratio(float(old.entry["val"]), float(new.entry["val"]))
            factor = factors[newer] * (ratio or 1.0)
            if ratio:
                splits.append(Split(concept, end, ratio, old.fact(concept), new.fact(concept)))
            break
        factors[accn] = factor
    return factors, splits


def _adjusted(fact: Fact, factors: dict[str, float]) -> Fact:
    factor = factors.get(fact.accession, 1.0)
    if factor == 1.0:
        return fact
    return replace(fact, value=fact.value * factor, split_factor=factor)


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
    filings, fiscal_ends = _index(sources)

    result = Statements(
        cik=sources[0].cik,
        name=docs[0].get("entityName", ""),
        facts={},
        fy_offset=_fy_offset(sources[0], filings),
        taxonomies={name: len(c) for name, c in docs[0].get("facts", {}).items()},
    )
    by_concept: dict[str, dict[date, list[_Candidate]]] = {}
    # Years each filing presents in its statements: any chain tag of any concept, kept apart
    # for balances (a balance sheet shows two year-ends, an income statement three). A note
    # that merely mentions an older year (2-year smaller-company statements) doesn't count.
    presented: dict[tuple[bool, str], set[date]] = defaultdict(set)
    for concept, chain in CHAINS.items():
        balance = concept in INSTANTS
        candidates = by_concept[concept] = defaultdict(list)
        for rank, tag in enumerate(chain):
            for source in sources:
                for period, entry in _reported(source, tag, concept, fiscal_ends):
                    filing = filings.get(entry["accn"])
                    if filing and in_window(period.end, filing.own_end, balance):
                        candidates[period.end].append(
                            _Candidate(rank, tag, period, entry, source.cik)
                        )
                        presented[(balance, entry["accn"])].add(period.end)

    software = _software(sources)
    for concept, candidates in by_concept.items():
        factors: dict[str, float] = {}
        if _unit(concept) == "shares":
            factors, splits = _split_factors(concept, candidates)
            result.splits.extend(splits)
        resolved: dict[date, Fact] = {}
        for end in sorted(candidates):
            found = candidates[end]
            newest = max(filing_key(c.entry) for c in found)
            in_filing = sorted(
                (c for c in found if filing_key(c.entry) == newest), key=lambda c: c.rank
            )
            winner = in_filing[0]
            chosen, problems = _resolve(concept, in_filing, software, factors)
            if chosen is None:
                continue
            resolved[end] = chosen
            result.flags.extend(Flag(concept, end, problem) for problem in problems)

            for other in [] if concept in SUMMED else in_filing[1:]:
                same_year = abs(other.period.start - winner.period.start) <= SAME_START
                other_fact = _adjusted(other.fact(concept), factors)
                if (
                    same_year
                    and other.tag != winner.tag
                    and other.tag not in NARROWER.get(concept, ())
                    and other_fact.value != chosen.value
                ):
                    result.conflicts.append(Conflict(concept, end, chosen, other_fact))

            newer = [
                f
                for f in filings.values()
                if (f.filed, f.accn) > newest and end in presented[(concept in INSTANTS, f.accn)]
            ]
            if newer:
                latest = max(newer, key=lambda f: (f.filed, f.accn))
                hints = _hints(sources, concept, latest.accn, end, fiscal_ends)
                stale = Stale(
                    concept, end, chosen, latest.accn, date.fromisoformat(latest.filed), hints
                )
                result.stale.append(stale)

            if winner.tag in CONTRACT_REVENUE:
                for source in sources:
                    for period, entry in _annual(source, NON_CONTRACT_REVENUE):
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
            before = _resolve(concept, restated, software, factors)[0]
            if before is None:
                continue
            change = pct_change(before.value, resolved[end].value)
            if change is not None and abs(change) > BREAK_THRESHOLD:
                result.breaks.append(Break(concept, end, prev_end, before, resolved[end]))

        result.facts[concept] = resolved
    return result
