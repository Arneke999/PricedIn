# PricedIn

A self-hosted stock research tool. It runs on your own machine as a local web app and
builds long-run fundamentals for US-listed companies from SEC filings.

**Status: early.** Charts revenue, operating margin and free cash flow for one company at a
time. A number is charted only once a golden test checks it against values computed by hand
from 10-K filings (`tests/golden/`). Not investment advice.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/). It installs everything else (Flask, pytest, ruff) into
  a project-local `.venv`, pinned by `uv.lock`. Nothing is installed system-wide.

**NixOS:** generic Linux binaries from PyPI (ruff now, DuckDB later) don't run without
`programs.nix-ld.enable = true;` in your system configuration. Pure-Python packages work
either way. If fetching fails with `CERTIFICATE_VERIFY_FAILED`, uv's Python can't find the
system CA bundle: set `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` in `.env`.

## Setup

```sh
cp .env.example .env
```

Set `SEC_USER_AGENT` in `.env` to your own name and contact email. The SEC requires one on
every request and rate-limits whoever it names, so never use someone else's.

## Run

```sh
uv run python -m pricedin
```

Open http://127.0.0.1:5000 and enter a ticker. The server only listens on localhost.

## Develop

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Data

- **SEC EDGAR** (`companyfacts`): public information, no key. Raw responses are archived
  under `raw/` before parsing and are never committed.
- Price and estimate sources come later, each optional and on your own free key. Their
  terms generally allow personal use only, so fetched data stays on your machine.

## License

MIT. ECharts is vendored under `pricedin/web/static/vendor/` (Apache-2.0).
