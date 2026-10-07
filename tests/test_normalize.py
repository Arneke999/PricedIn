import json
from datetime import date

from pricedin.normalize import edgar
from pricedin.normalize.restated import latest_annual
from pricedin.normalize.schema import Period

FY2023 = Period(date(2023, 1, 1), date(2023, 12, 31))
FY2024 = Period(date(2024, 1, 1), date(2024, 12, 31))


def entry(val, start, end, form, filed, accn="0000000000-00-000000"):
    return {"val": val, "start": start, "end": end, "form": form, "filed": filed, "accn": accn}


def companyfacts(tags: dict[str, list[dict]]) -> bytes:
    facts = {tag: {"units": {"USD": entries}} for tag, entries in tags.items()}
    return json.dumps({"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": facts}}).encode()


def test_latest_restated_value_wins():
    entries = [
        entry(100, "2023-01-01", "2023-12-31", "10-K", "2024-02-01", "a"),
        entry(95, "2023-01-01", "2023-12-31", "10-K", "2025-02-01", "b"),  # restated
    ]
    assert latest_annual(entries)[FY2023]["val"] == 95


def test_quarters_and_non_annual_forms_are_ignored():
    entries = [
        entry(25, "2024-10-01", "2024-12-31", "10-K", "2025-02-01"),  # Q4 inside a 10-K
        entry(90, "2024-01-01", "2024-12-31", "8-K", "2025-03-01"),  # recast in an 8-K
        entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01"),
    ]
    picked = latest_annual(entries)
    assert list(picked) == [FY2024]
    assert picked[FY2024]["val"] == 100


def test_amended_10k_counts():
    entries = [
        entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01"),
        entry(101, "2024-01-01", "2024-12-31", "10-K/A", "2025-04-01"),
    ]
    assert latest_annual(entries)[FY2024]["val"] == 101


def test_chain_falls_back_per_period():
    body = companyfacts(
        {
            "SalesRevenueNet": [entry(80, "2023-01-01", "2023-12-31", "10-K", "2024-02-01")],
            "Revenues": [entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01")],
        }
    )
    revenue = edgar.statements(body).series("revenue")
    assert revenue[FY2023].source_tag == "SalesRevenueNet"
    assert revenue[FY2024].source_tag == "Revenues"


def test_disagreeing_tags_are_recorded_as_conflicts():
    body = companyfacts(
        {
            "Revenues": [entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01")],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry(97, "2024-01-01", "2024-12-31", "10-K", "2025-02-01")
            ],
        }
    )
    stmts = edgar.statements(body)
    assert stmts.series("revenue")[FY2024].value == 100
    [conflict] = stmts.conflicts
    assert conflict.other.value == 97


def test_ticker_index():
    body = json.dumps({"0": {"cik_str": 1652044, "ticker": "googl", "title": "Alphabet Inc."}})
    assert edgar.ticker_index(body.encode())["GOOGL"] == (1652044, "Alphabet Inc.")
