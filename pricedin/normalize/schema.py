"""Canonical statement schema. Nothing downstream of normalize/ knows which vendor a
number came from; the provenance fields exist so a number can be checked by hand."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, order=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
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


@dataclass(frozen=True)
class Conflict:
    """Two tags in one concept's chain report different values for the same period."""

    concept: str
    period: Period
    chosen: Fact
    other: Fact


@dataclass(frozen=True)
class Statements:
    cik: int
    name: str
    # concept -> period -> fact, periods sorted ascending
    facts: dict[str, dict[Period, Fact]]
    conflicts: list[Conflict] = field(default_factory=list)

    def series(self, concept: str) -> dict[Period, Fact]:
        return self.facts.get(concept, {})
