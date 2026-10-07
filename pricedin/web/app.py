"""Local web app. Views assemble what metrics/ computed; templates only format it."""

from __future__ import annotations

import urllib.error

from flask import Flask, redirect, render_template, request, url_for

from pricedin import config
from pricedin.data import archive, edgar
from pricedin.metrics.cash_flow import free_cash_flow
from pricedin.metrics.margins import operating_margin
from pricedin.normalize import edgar as normalize_edgar
from pricedin.normalize.schema import Fact, Period

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


def _point(period: Period, value: float, sources: list[Fact]) -> dict:
    return {
        "label": f"FY{period.end.year}",
        "end": period.end.isoformat(),
        "value": value,
        "sources": [
            f"{f.source_tag}: {f.form} filed {f.filed.isoformat()}, accn {f.accession}"
            for f in sources
        ],
    }


@app.get("/")
def index():
    ticker = request.args.get("ticker", "").strip().upper()
    if ticker:
        return redirect(url_for("company", ticker=ticker))
    return render_template("index.html", ua_error=_user_agent_status())


@app.get("/company/<ticker>")
def company(ticker: str):
    ticker = ticker.upper()
    ctx = {"ticker": ticker, "ua_error": _user_agent_status(), "error": request.args.get("error")}

    if archive.latest(edgar.TICKERS_KIND) is None:
        return render_template("company.html", state="not_fetched", **ctx)
    found = _lookup(ticker)
    if found is None:
        return render_template("company.html", state="unknown_ticker", **ctx), 404
    cik, _ = found
    cached = archive.latest(edgar.companyfacts_kind(cik))
    if cached is None:
        return render_template("company.html", state="not_fetched", cik=cik, **ctx)

    body, manifest_entry = cached
    stmts = normalize_edgar.statements(body)
    revenue = stmts.series("revenue")
    op_income = stmts.series("operating_income")
    ocf = stmts.series("operating_cash_flow")
    capex = stmts.series("capex")

    charts = {
        "revenue": [_point(p, f.value, [f]) for p, f in revenue.items()],
        "operating_margin": [
            _point(p, v, [revenue[p], op_income[p]])
            for p, v in operating_margin(revenue, op_income).items()
        ],
        "fcf": [_point(p, v, [ocf[p], capex[p]]) for p, v in free_cash_flow(ocf, capex).items()],
    }
    return render_template(
        "company.html",
        state="ok",
        cik=cik,
        name=stmts.name,
        fetched_at=manifest_entry["fetched_at"],
        charts=charts,
        conflicts=stmts.conflicts,
        **ctx,
    )


@app.post("/company/<ticker>/refresh")
def refresh(ticker: str):
    ticker = ticker.upper()
    try:
        if archive.latest(edgar.TICKERS_KIND) is None:
            edgar.fetch_tickers()
        found = _lookup(ticker)
        if found is not None:
            edgar.fetch_companyfacts(found[0])
    except config.ConfigError as e:
        return redirect(url_for("company", ticker=ticker, error=str(e)))
    except (urllib.error.URLError, TimeoutError) as e:
        return redirect(url_for("company", ticker=ticker, error=f"SEC fetch failed: {e}"))
    return redirect(url_for("company", ticker=ticker))
