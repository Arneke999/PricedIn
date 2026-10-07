"""Local web app. Views assemble what normalize/ and metrics/ computed; templates only
format it."""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass, field
from datetime import date

from flask import Flask, redirect, render_template, request, url_for

from pricedin import config
from pricedin.data import archive, edgar
from pricedin.metrics.cash_flow import free_cash_flow
from pricedin.metrics.margins import operating_margin
from pricedin.normalize import edgar as normalize_edgar
from pricedin.normalize.predecessors import PREDECESSORS, Predecessor, successor_signals
from pricedin.normalize.schema import Fact, Statements
from pricedin.normalize.scope import Scope, classify
from pricedin.normalize.tags import CHAINS

app = Flask(__name__)


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
    taxonomies: dict[str, int] = field(default_factory=dict)
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
    company.taxonomies = normalize_edgar.taxonomies(body)
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


def _warnings(stmts: Statements, concepts: set[str], ends: set[date]) -> list[str]:
    """Plain-language notes about breaks, stale values and flags shown on one chart."""
    notes = []
    for b in stmts.breaks:
        if b.concept in concepts and b.end in ends:
            notes.append(
                f"{stmts.label(b.prev_end)} → {stmts.label(b.end)}: basis change in "
                f"{b.concept.replace('_', ' ')}. The 10-K filed {b.after.filed} restated "
                f"{stmts.label(b.end)} from {_usd(b.before.value)} to {_usd(b.after.value)} "
                f"({b.change:+.1%}); {stmts.label(b.prev_end)} and earlier are on the old "
                "basis, so growth across this point isn't comparable."
            )
    for s in stmts.stale:
        if s.concept in concepts and s.end in ends:
            hint = ", ".join(f"{tag} = {_usd(v)}" for tag, v in s.hints[:2])
            notes.append(
                f"{stmts.label(s.end)} {s.concept.replace('_', ' ')} may be outdated: the 10-K "
                f"filed {s.newer_filed} (accn {s.newer_accession}) reports this year, but not "
                f"under the tags PricedIn reads. Shown: {_usd(s.used.value)} from the 10-K "
                f"filed {s.used.filed}." + (f" Related tags there: {hint}." if hint else "")
            )
    for f in stmts.flags:
        if f.concept in concepts and f.end in ends:
            notes.append(f"{stmts.label(f.end)}: {f.message}")
    return notes


def _chart(stmts: Statements, values: dict[date, float], inputs: list[dict[date, Fact]]):
    concepts = {series[end].concept for series in inputs for end in values}
    stale = {(s.concept, s.end) for s in stmts.stale}
    points = []
    for end, value in values.items():
        facts = [series[end] for series in inputs]
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
                    for f in facts
                ],
            }
        )
    breaks = sorted(
        {stmts.label(b.end) for b in stmts.breaks if b.concept in concepts and b.end in values}
    )
    return {
        "points": points,
        "breaks": breaks,
        "warnings": _warnings(stmts, concepts, set(values)),
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
    revenue, op_income = s.series("revenue"), s.series("operating_income")
    ocf, capex = s.series("operating_cash_flow"), s.series("capex")
    charts = {
        "revenue": _chart(s, {e: f.value for e, f in revenue.items()}, [revenue]),
        "operating_margin": _chart(s, operating_margin(revenue, op_income), [revenue, op_income]),
        "fcf": _chart(s, free_cash_flow(ocf, capex), [ocf, capex]),
    }
    return render_template(
        "company.html",
        state=state,
        charts=charts,
        capex_missing=bool(ocf) and not capex,
        no_revenue=any(f.value <= 0 for f in revenue.values()),
        **ctx,
    )


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
        co=co,
        ticker=co.ticker,
        state=state,
        concepts=concepts,
        chains=CHAINS,
        rows=rows,
        stale=stale,
        conflicts=conflicts,
        usd=_usd,
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
