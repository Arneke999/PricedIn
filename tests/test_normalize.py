import json
from datetime import date

from pricedin.normalize import edgar
from pricedin.normalize.schema import Period

FY2023 = Period(date(2023, 1, 1), date(2023, 12, 31))
FY2024 = Period(date(2024, 1, 1), date(2024, 12, 31))


def entry(val, start, end, form, filed, accn="0000000000-00-000000"):
    return {"val": val, "start": start, "end": end, "form": form, "filed": filed, "accn": accn}


def companyfacts(tags: dict[str, list[dict]]) -> bytes:
    facts = {tag: {"units": {"USD": entries}} for tag, entries in tags.items()}
    return json.dumps({"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": facts}}).encode()


def revenue(tags: dict[str, list[dict]]):
    return edgar.statements(companyfacts(tags)).series("revenue")


def test_latest_restated_value_wins():
    rev = revenue(
        {
            "Revenues": [
                entry(100, "2023-01-01", "2023-12-31", "10-K", "2024-02-01", "a"),
                entry(95, "2023-01-01", "2023-12-31", "10-K", "2025-02-01", "b"),  # restated
            ]
        }
    )
    assert rev[FY2023].value == 95


def test_newer_filing_beats_higher_ranked_tag():
    # The old filing used the chain's first tag; the restated value sits under a later tag.
    rev = revenue(
        {
            "Revenues": [entry(100, "2023-01-01", "2023-12-31", "10-K", "2024-02-01", "a")],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry(95, "2023-01-01", "2023-12-31", "10-K", "2025-02-01", "b")
            ],
        }
    )
    assert rev[FY2023].value == 95


def test_quarters_and_non_annual_forms_are_ignored():
    rev = revenue(
        {
            "Revenues": [
                entry(25, "2024-10-01", "2024-12-31", "10-K", "2025-02-01"),  # Q4 in a 10-K
                entry(90, "2024-01-01", "2024-12-31", "8-K", "2025-03-01"),  # 8-K recast
                entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01"),
            ]
        }
    )
    assert list(rev) == [FY2024]
    assert rev[FY2024].value == 100


def test_amended_10k_counts():
    rev = revenue(
        {
            "Revenues": [
                entry(100, "2024-01-01", "2024-12-31", "10-K", "2025-02-01", "a"),
                entry(101, "2024-01-01", "2024-12-31", "10-K/A", "2025-04-01", "b"),
            ]
        }
    )
    assert rev[FY2024].value == 101


def test_restatement_across_filings_is_not_a_conflict():
    body = companyfacts(
        {
            "Revenues": [entry(100, "2023-01-01", "2023-12-31", "10-K", "2024-02-01", "a")],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry(95, "2023-01-01", "2023-12-31", "10-K", "2025-02-01", "b")
            ],
        }
    )
    assert edgar.statements(body).conflicts == []


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
