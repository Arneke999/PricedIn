"""Canonical statement schema. Nothing downstream of normalize/ knows which vendor a
number came from; the provenance fields exist so a number can be checked by hand.

A fiscal year is identified by its end date (DECISIONS #28), so every series is keyed by
`date`. `Fact.period` keeps the start date for display and duration checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, order=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        """end - start, so a 52-week year is 363 and a 53-week year 370."""
        return (self.end - self.start).days


@dataclass(frozen=True)
class Fact:
    concept: str
    period: Period
    value: float
    unit: str
    source_tag: str
    accession: str
    form: str
    filed: date
    cik: int
    # Earlier years of a share count are multiplied onto the latest basis (DECISIONS #50)
    split_factor: float = 1.0

    @property
    def as_reported(self) -> float:
        """The value as the filing printed it, before any split adjustment."""
        return self.value / self.split_factor


def pct_change(old: float, new: float) -> float | None:
    return (new - old) / abs(old) if old else None


@dataclass(frozen=True)
class Conflict:
    """Two chain tags in the same filing report different values for the same year."""

    concept: str
    end: date
    chosen: Fact
    other: Fact

    @property
    def gap(self) -> float | None:
        return pct_change(self.chosen.value, self.other.value)


@dataclass(frozen=True)
class Break:
    """The basis changed between two adjacent years (DECISIONS #24).

    `before` is the older filing's value for year `end`; `after` is the value we use. The
    previous year still sits on the older filing's basis.
    """

    concept: str
    end: date
    prev_end: date
    before: Fact
    after: Fact

    @property
    def change(self) -> float | None:
        return pct_change(self.before.value, self.after.value)


@dataclass(frozen=True)
class Split:
    """A newer 10-K restated a share count by a stock-split ratio (DECISIONS #50).

    `before` and `after` are year `end` as the older and newer filing reported it. Values
    from the older filing and those before it are multiplied by `ratio` (times any later
    splits) to put them on the newest basis; `Fact.split_factor` holds the product.
    """

    concept: str
    end: date
    ratio: float
    before: Fact
    after: Fact


@dataclass(frozen=True)
class Stale:
    """A newer 10-K reports this year, but under none of the chain's tags (DECISIONS #25)."""

    concept: str
    end: date
    used: Fact
    newer_accession: str
    newer_filed: date
    hints: tuple[tuple[str, float], ...]  # (tag, value) in the newer filing that look like it


@dataclass(frozen=True)
class Flag:
    concept: str
    end: date
    message: str


@dataclass(frozen=True)
class Statements:
    cik: int
    name: str
    # concept -> fiscal-year end -> fact, ascending
    facts: dict[str, dict[date, Fact]]
    conflicts: list[Conflict] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    stale: list[Stale] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    # Company naming: label year = nominal year of the end date + offset (DECISIONS #29)
    fy_offset: int = 0
    # Taxonomy -> concepts the primary filer reports, e.g. {"us-gaap": 503, "dei": 2}
    taxonomies: dict[str, int] = field(default_factory=dict)

    def series(self, concept: str) -> dict[date, Fact]:
        return self.facts.get(concept, {})

    def label(self, end: date) -> str:
        from pricedin.normalize.restated import nominal_year

        return self.year_label(nominal_year(end))

    def year_label(self, nominal_year: int) -> str:
        return f"FY{nominal_year + self.fy_offset}"
