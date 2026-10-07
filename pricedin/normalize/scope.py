"""Which companies PricedIn covers, decided from a company's `submissions` JSON.

Financials are excluded by SIC code (DECISIONS #20, #37) and foreign filers by the forms
they file (#21). A manual override per CIK sits on top of both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

EXCLUDED_SIC: dict[str, str] = {
    "6021": "bank",
    "6022": "bank",
    "6029": "bank",
    "6035": "bank",
    "6036": "bank",
    "6311": "insurer",
    "6321": "insurer",
    "6331": "insurer",
    "6351": "insurer",
    "6361": "insurer",
    "6399": "insurer",
    "6798": "REIT",
    "6770": "blank check",
}

# CIK -> ("exclude" | "include", reason). An exclude reason must be a key of MESSAGES.
# An override beats both the SIC list and the foreign-filer check.
OVERRIDES: dict[int, tuple[str, str]] = {
    1067983: ("exclude", "holdco"),  # Berkshire Hathaway: SIC 6331, but a conglomerate
}

MESSAGES: dict[str, str] = {
    "bank": "PricedIn doesn't cover banks yet: they have no operating income and no "
    "meaningful free cash flow, so the standard charts would mislead.",
    "insurer": "PricedIn doesn't cover insurers yet: premiums, claims and investment income "
    "don't fit operating income and free cash flow, so the standard charts would mislead.",
    "REIT": "PricedIn doesn't cover REITs yet: they're judged on funds from operations, not "
    "operating income and free cash flow, so the standard charts would mislead.",
    "blank check": "PricedIn doesn't cover blank-check companies (SPACs): they hold cash in "
    "trust and have no operating business to chart.",
    "holdco": "PricedIn doesn't cover this holding company yet: its statements mix insurance, "
    "finance and operating businesses, so operating income and free cash flow would mislead.",
    "foreign filer": "PricedIn doesn't cover foreign filers yet: this company files its annual "
    "report on Form 20-F or 40-F, often under IFRS, which PricedIn doesn't read.",
}

FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}
DOMESTIC_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A"}

# Long enough to hold two annual reports even if one was filed late. It's measured back
# from the company's newest filing, not from today, so the result depends only on the body.
# `filings.recent` always spans at least a year (SEC), so it holds the latest annual report.
FOREIGN_WINDOW = timedelta(days=3 * 365)


@dataclass(frozen=True)
class Scope:
    cik: int
    sic: str | None
    sic_description: str | None
    status: str  # "covered" | "excluded"
    category: str | None  # "bank", "insurer", "REIT", "blank check", "holdco", "foreign filer"
    message: str | None  # the user-facing reason, None when covered


def is_foreign_filer(submissions: dict) -> bool:
    """A 20-F or 40-F in the window and no 10-K in it."""
    recent = submissions.get("filings", {}).get("recent", {})
    filed = [date.fromisoformat(d) for d in recent.get("filingDate", [])]
    if not filed:
        return False
    since = max(filed) - FOREIGN_WINDOW
    forms = {form for form, day in zip(recent.get("form", []), filed, strict=True) if day >= since}
    return bool(forms & FOREIGN_FORMS) and not forms & DOMESTIC_FORMS


def classify(submissions_body: bytes) -> Scope:
    data = json.loads(submissions_body)
    cik = int(data["cik"])
    sic = data.get("sic") or None
    description = data.get("sicDescription") or None

    def scope(category: str | None) -> Scope:
        if category is None:
            return Scope(cik, sic, description, "covered", None, None)
        return Scope(cik, sic, description, "excluded", category, MESSAGES[category])

    if cik in OVERRIDES:
        action, reason = OVERRIDES[cik]
        return scope(reason if action == "exclude" else None)
    if sic in EXCLUDED_SIC:
        return scope(EXCLUDED_SIC[sic])
    if is_foreign_filer(data):
        return scope("foreign filer")
    return scope(None)
