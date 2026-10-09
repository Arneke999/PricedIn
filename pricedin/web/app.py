"""Local web app. Views assemble what normalize/ and metrics/ computed; templates only
format it."""

from __future__ import annotations

import urllib.error
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

from flask import Flask, redirect, render_template, request, url_for

from pricedin import config
from pricedin.data import archive, edgar
from pricedin.metrics.verified import VERIFIED
from pricedin.normalize import edgar as normalize_edgar
from pricedin.normalize.predecessors import PREDECESSORS, Predecessor, successor_signals
from pricedin.normalize.restated import nominal_year
from pricedin.normalize.schema import Statements
from pricedin.normalize.scope import Scope, classify
from pricedin.normalize.tags import CHAINS

app = Flask(__name__)

# Company page charts in order: (series, title, ECharts type, subtitle). Every series must be
# in VERIFIED, which only golden-tested series enter (display gate, DECISIONS #17).
COMPANY_CHARTS = (
    ("revenue", "Revenue", "bar", None),
    ("operating_margin", "Operating margin", "line", None),
    ("net_income", "Net income", "bar", "(attributable to the company)"),
    (
        "fcf",
        "Free cash flow",
        "bar",
        "(operating cash flow, continuing operations first, minus capex; SBC not deducted)",
    ),
    ("sbc", "Stock-based compensation", "bar", "(the add-back on the cash flow statement)"),
    ("diluted_shares", "Diluted shares", "line", "(weighted average for the year)"),
)


def _user_agent_status() -> str | None:
    """None when the SEC User-Agent is configured, else the message explaining how."""
    try:
        config.sec_user_agent()
    except config.ConfigError as e:
        return str(e)
    return None


def _lookup(ticker: str) -> tuple[int, str] | None:
    cached = archive.latest(edgar.TICKERS_KIND)
    if cached is None:
        return None
    return normalize_edgar.ticker_index(cached[0]).get(ticker)


@dataclass
class _Company:
    ticker: str
    cik: int | None = None
    name: str | None = None
    scope: Scope | None = None
    stmts: Statements | None = None
    fetched_at: str | None = None
    predecessors: tuple[Predecessor, ...] = ()
    signals: list[str] = field(default_factory=list)


def _load(ticker: str) -> tuple[str, _Company]:
    """State ("not_fetched", "unknown_ticker", "excluded", "ok") and what's known."""
    company = _Company(ticker)
    if archive.latest(edgar.TICKERS_KIND) is None:
        return "not_fetched", company
    found = _lookup(ticker)
    if found is None:
        return "unknown_ticker", company
    company.cik, company.name = found

    submissions = archive.latest(edgar.submissions_kind(company.cik))
    if submissions:
        company.scope = classify(submissions[0])
    facts = archive.latest(edgar.companyfacts_kind(company.cik))
    if facts is None:
        return "not_fetched", company

    body, manifest_entry = facts
    company.fetched_at = manifest_entry["fetched_at"]
    company.predecessors = PREDECESSORS.get(company.cik, ())
    older = [archive.latest(edgar.companyfacts_kind(p.cik)) for p in company.predecessors]
    company.stmts = normalize_edgar.statements(body, [c[0] for c in older if c])
    if submissions:
        years = max((len(s) for s in company.stmts.facts.values()), default=0)
        company.signals = successor_signals(ticker, company.cik, submissions[0], years)

    excluded = company.scope is not None and company.scope.status == "excluded"
    return ("excluded" if excluded else "ok"), company


def _usd(value: float) -> str:
    if abs(value) >= 1e9:
        return f"${value / 1e9:,.1f}B"
    return f"${value / 1e6:,.0f}M"


def _amount(value: float, unit: str) -> str:
    return f"{value / 1e6:,.0f}M shares" if unit == "shares" else _usd(value)


def _ratio(factor: float) -> str:
    """A split factor as a ratio: 4.0 -> "4:1", 0.125 -> "1:8"."""
    f = Fraction(factor).limit_denominator(1000)
    return f"{f.numerator}:{f.denominator}"


def _warnings(stmts: Statements, concepts: set[str], ends: set[date]) -> list[str]:
    """Plain-language notes about breaks, stale values and flags shown on one chart."""
    notes = []
    for b in stmts.breaks:
        if b.concept in concepts and b.end in ends:
            notes.append(
                f"{stmts.label(b.prev_end)} → {stmts.label(b.end)}: basis change in "
                f"{b.concept.replace('_', ' ')}. The 10-K filed {b.after.filed} restated "
                f"{stmts.label(b.end)} from {_amount(b.before.value, b.before.unit)} to "
                f"{_amount(b.after.value, b.after.unit)} "
                f"({b.change:+.1%}); {stmts.label(b.prev_end)} and earlier are on the old "
                "basis, so growth across this point isn't comparable."
            )
    for s in stmts.stale:
        if s.concept in concepts and s.end in ends:
            hint = ", ".join(tag for tag, _ in s.hints[:2])
            notes.append(
                f"{stmts.label(s.end)} {s.concept.replace('_', ' ')} may be outdated: the 10-K "
                f"filed {s.newer_filed} (accn {s.newer_accession}) reports this year, but not "
                f"under the tags PricedIn reads. Shown: {_amount(s.used.value, s.used.unit)} "
                "from the 10-K "
                f"filed {s.used.filed}."
                + (f" Related tags there (values on the coverage page): {hint}." if hint else "")
            )
    for concept in sorted(concepts):
        by_factor: dict[float, list[date]] = defaultdict(list)
        for end, fact in stmts.series(concept).items():
            if end in ends and fact.split_factor != 1:
                by_factor[fact.split_factor].append(end)
        if not by_factor:
            continue
        spans = ", ".join(
            f"{_span(stmts, years)} {_ratio(factor)}" for factor, years in by_factor.items()
        )
        found = "; ".join(
            f"{_ratio(sp.ratio)} (the 10-K filed {sp.after.filed} restated "
            f"{stmts.label(sp.end)} from {_amount(sp.before.value, sp.before.unit)} to "
            f"{_amount(sp.after.value, sp.after.unit)})"
            for sp in stmts.splits
            if sp.concept == concept
        )
        notes.append(
            f"Split-adjusted {concept.replace('_', ' ')}: {spans}, so earlier years compare "
            f"with later ones. Splits found: {found}."
        )
    for f in stmts.flags:
        if f.concept in concepts and f.end in ends:
            notes.append(f"{stmts.label(f.end)}: {f.message}")
    return notes


def _span(stmts: Statements, ends: list[date]) -> str:
    first, last = stmts.label(min(ends)), stmts.label(max(ends))
    return first if first == last else f"{first}–{last}"


def _chart(stmts: Statements, name: str, title: str, kind: str, subtitle: str | None):
    series = VERIFIED[name]
    values = series.values(stmts)
    inputs = [stmts.series(c) for c in series.inputs]
    concepts = {by_end[end].concept for by_end in inputs for end in values}
    stale = {(s.concept, s.end) for s in stmts.stale}
    points, gaps = [], []
    ends = list(values)
    for prev, end in zip([None, *ends], ends, strict=False):
        # Missing years stay visible as empty slots (DECISIONS #51)
        years = range(nominal_year(prev) + 1, nominal_year(end)) if prev else range(0)
        missing = [stmts.year_label(y) for y in years]
        if missing:
            gaps.append(missing[0] if len(missing) == 1 else f"{missing[0]}–{missing[-1]}")
            points.extend({"label": label, "value": None, "stale": False} for label in missing)
        facts = [by_end[end] for by_end in inputs]
        value = values[end]
        points.append(
            {
                "label": stmts.label(end),
                "end": end.isoformat(),
                "value": value,
                "weeks53": facts[0].period.days >= 370,
                "stale": any((f.concept, end) in stale for f in facts),
                "mixed": len({f.accession for f in facts}) > 1,
                "sources": [
                    f"{f.source_tag}: {f.form} filed {f.filed.isoformat()}, accn {f.accession}"
                    + (f", split-adjusted {_ratio(f.split_factor)}" if f.split_factor != 1 else "")
                    for f in facts
                ],
            }
        )
    breaks = sorted(
        {stmts.label(b.end) for b in stmts.breaks if b.concept in concepts and b.end in values}
    )
    return {
        "id": name,
        "title": title,
        "kind": kind,
        "subtitle": subtitle,
        "unit": series.unit,
        "points": points,
        "breaks": breaks,
        "warnings": _warnings(stmts, concepts, set(values))
        + [
            f"No data for {g}. Years on either side may be on different bases (a stock split, "
            "for instance), so growth isn't computed across the gap."
            for g in gaps
        ],
        "note": None,  # shown above the chart
        "unavailable": None,  # shown instead of the chart
    }


@app.get("/")
def index():
    ticker = request.args.get("ticker", "").strip().upper()
    if ticker:
        return redirect(url_for("company", ticker=ticker))
    return render_template("index.html", ua_error=_user_agent_status())


@app.get("/company/<ticker>")
def company(ticker: str):
    state, co = _load(ticker.upper())
    ctx = {"co": co, "ticker": co.ticker, "ua_error": _user_agent_status()}
    ctx["error"] = request.args.get("error")
    if state != "ok":
        return render_template("company.html", state=state, **ctx), (
            404 if state == "unknown_ticker" else 200
        )

    s = co.stmts
    charts = {spec[0]: _chart(s, *spec) for spec in COMPANY_CHARTS}
    if any(f.value <= 0 for f in s.series("revenue").values()):
        charts["operating_margin"]["note"] = (
            "Margins aren't computed for years with zero or negative revenue."
        )
    if not s.series("sbc"):
        charts["sbc"]["unavailable"] = (
            "This company's cash flow statement doesn't report stock-based compensation under "
            "the standard tag PricedIn reads, so it isn't shown."
        )
    if s.series("operating_cash_flow") and not s.series("capex"):
        charts["fcf"]["unavailable"] = (
            "Capex isn't reported in SEC structured data for this company, so free cash flow "
            "can't be computed."
        )
    return render_template("company.html", state=state, charts=list(charts.values()), **ctx)


@app.get("/company/<ticker>/coverage")
def coverage(ticker: str):
    """Every canonical line item per year, with the tag and filing it came from."""
    state, co = _load(ticker.upper())
    if co.stmts is None:
        return redirect(url_for("company", ticker=co.ticker))

    s = co.stmts
    concepts = list(CHAINS)
    ends = sorted({e for c in concepts for e in s.series(c)})
    rows = [(e, s.label(e), [s.series(c).get(e) for c in concepts]) for e in ends]
    stale = {(x.concept, x.end) for x in s.stale}
    conflicts = sorted(s.conflicts, key=lambda c: -abs(c.gap or 0))
    return render_template(
        "coverage.html",
        untested=[c for c in concepts if c not in VERIFIED],
        co=co,
        ticker=co.ticker,
        state=state,
        concepts=concepts,
        chains=CHAINS,
        rows=rows,
        stale=stale,
        conflicts=conflicts,
        amount=_amount,
        ratio=_ratio,
        ua_error=_user_agent_status(),
    )


@app.post("/company/<ticker>/refresh")
def refresh(ticker: str):
    ticker = ticker.upper()
    try:
        if archive.latest(edgar.TICKERS_KIND) is None:
            edgar.fetch_tickers()
        found = _lookup(ticker)
        if found is not None:
            cik = found[0]
            edgar.fetch_companyfacts(cik)
            edgar.fetch_submissions(cik)
            for p in PREDECESSORS.get(cik, ()):
                if archive.latest(edgar.companyfacts_kind(p.cik)) is None:
                    edgar.fetch_companyfacts(p.cik)
    except config.ConfigError as e:
        return redirect(url_for("company", ticker=ticker, error=str(e)))
    except (urllib.error.URLError, TimeoutError) as e:
        return redirect(url_for("company", ticker=ticker, error=f"SEC fetch failed: {e}"))
    return redirect(url_for("company", ticker=ticker))
