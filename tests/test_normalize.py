import json
from datetime import date

import pytest

from pricedin.normalize import edgar

Y2019, Y2020 = date(2019, 12, 31), date(2020, 12, 31)
Y2021, Y2022 = date(2021, 12, 31), date(2022, 12, 31)
Y2023, Y2024 = date(2023, 12, 31), date(2024, 12, 31)


def entry(val, year, form="10-K", filed=None, accn="a", start=None, end=None, fy=None):
    """A full calendar-year fact. `filed` defaults to early the following year."""
    return {
        "val": val,
        "start": start or f"{year}-01-01",
        "end": end or f"{year}-12-31",
        "form": form,
        "filed": filed or f"{year + 1}-02-01",
        "accn": accn,
        "fy": fy,
    }


def companyfacts(tags: dict[str, list[dict]], cik=1, unit="USD") -> bytes:
    facts = {tag: {"units": {unit: entries}} for tag, entries in tags.items()}
    return json.dumps({"cik": cik, "entityName": "Test Co", "facts": {"us-gaap": facts}}).encode()


def resolve(tags, **kwargs):
    return edgar.statements(companyfacts(tags), **kwargs)


def test_latest_restated_value_wins():
    s = resolve({"Revenues": [entry(100, 2023), entry(95, 2023, filed="2025-02-01", accn="b")]})
    assert s.series("revenue")[Y2023].value == 95


def test_newer_filing_beats_higher_ranked_tag():
    s = resolve(
        {
            "Revenues": [entry(100, 2023)],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry(95, 2023, filed="2025-02-01", accn="b"),
                entry(99, 2024, accn="b"),
            ],
        }
    )
    assert s.series("revenue")[Y2023].value == 95


def test_quarters_proxy_statements_and_8k_recasts_are_ignored():
    s = resolve(
        {
            "Revenues": [entry(100, 2024)],
            "NetIncomeLoss": [
                entry(10, 2024),
                entry(25, 2024, start="2024-10-01"),  # Q4 inside the 10-K
                entry(11, 2024, form="DEF 14A", filed="2025-04-01", accn="p"),
                entry(12, 2024, form="8-K", filed="2025-03-01", accn="r"),
            ],
        }
    )
    assert s.series("net_income")[Y2024].value == 10


def test_amended_10k_counts():
    s = resolve({"Revenues": [entry(100, 2024), entry(101, 2024, "10-K/A", "2025-04-01", "b")]})
    assert s.series("revenue")[Y2024].value == 101


def test_future_dated_facts_are_dropped():
    s = resolve({"Revenues": [entry(100, 2024), entry(500, 2025, filed="2025-02-01", accn="x")]})
    assert list(s.series("revenue")) == [Y2024]


def test_years_are_identified_by_end_date():
    # Some filings start the year on Dec 31 instead of Jan 1 (NEE).
    s = resolve(
        {
            "Revenues": [
                entry(100, 2010, start="2009-12-31", filed="2011-02-01", accn="a"),
                entry(98, 2010, filed="2012-02-01", accn="b"),
                entry(105, 2011, filed="2012-02-01", accn="b"),
            ]
        }
    )
    assert list(s.series("revenue")) == [date(2010, 12, 31), date(2011, 12, 31)]
    assert s.series("revenue")[date(2010, 12, 31)].value == 98


def test_values_older_than_a_filings_last_three_years_are_ignored():
    # The 2025 10-K also tags 2021 in a five-year summary; only its last 3 years count.
    s = resolve(
        {
            "Revenues": [
                entry(100, 2021, accn="a"),
                entry(999, 2021, filed="2026-02-01", accn="c"),
                entry(140, 2025, filed="2026-02-01", accn="c"),
            ]
        }
    )
    assert s.series("revenue")[Y2021].value == 100


def test_recast_break_is_detected():
    # The 2024 10-K recasts 2023 after a spin-off; 2022 stays on the old basis.
    s = resolve(
        {
            "Revenues": [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(110, 2023, filed="2024-02-01", accn="a"),
                entry(80, 2023, filed="2025-02-01", accn="b"),
                entry(90, 2024, filed="2025-02-01", accn="b"),
            ]
        }
    )
    [brk] = s.breaks
    assert (brk.prev_end, brk.end) == (Y2022, Y2023)
    assert (brk.before.value, brk.after.value) == (110, 80)


def test_small_restatements_are_not_breaks():
    s = resolve(
        {
            "Revenues": [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(1000, 2023, filed="2024-02-01", accn="a"),
                entry(1001, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.breaks == []


def test_stale_value_is_flagged_with_hints():
    # The newer 10-K restates 2019 revenue under a tag outside the chain.
    s = resolve(
        {
            "Revenues": [entry(100, 2019, accn="a")],
            "RevenuesNetOfInterestExpense": [
                entry(102, 2019, filed="2021-02-01", accn="b"),
                entry(110, 2020, accn="b"),
            ],
            "NetIncomeLoss": [
                entry(10, 2019, accn="a"),
                entry(10, 2019, filed="2021-02-01", accn="b"),
                entry(12, 2020, accn="b"),
            ],
        }
    )
    assert s.series("revenue")[Y2019].value == 100
    [stale] = [x for x in s.stale if x.concept == "revenue"]
    assert stale.newer_accession == "b"
    assert ("RevenuesNetOfInterestExpense", 102.0) in stale.hints


def test_contract_revenue_flagged_when_other_revenue_reported():
    s = resolve(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [entry(90, 2024)],
            "RevenueNotFromContractWithCustomer": [entry(10, 2024)],
        }
    )
    [flag] = s.flags
    assert (flag.concept, flag.end) == ("revenue", Y2024)


def test_disagreeing_tags_in_one_filing_are_conflicts():
    s = resolve(
        {
            "Revenues": [entry(100, 2024)],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [entry(97, 2024)],
        }
    )
    assert s.series("revenue")[Y2024].value == 100
    [conflict] = s.conflicts
    assert conflict.other.value == 97
    assert round(conflict.gap, 2) == -0.03


def test_restatement_across_filings_is_not_a_conflict():
    s = resolve(
        {
            "Revenues": [entry(100, 2023)],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                entry(95, 2023, filed="2025-02-01", accn="b")
            ],
        }
    )
    assert s.conflicts == []


def test_continuing_operations_cash_flow_comes_first():
    s = resolve(
        {
            "NetCashProvidedByUsedInOperatingActivities": [entry(5189, 2023)],
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": [entry(4609, 2023)],
        }
    )
    assert s.series("operating_cash_flow")[Y2023].value == 4609


def test_labels_follow_start_year_naming():
    # Target: the year ending 2026-01-31 is "fiscal 2025".
    s = resolve(
        {
            "Revenues": [
                entry(
                    100, 2024, start="2024-02-04", end="2025-02-01", filed="2026-03-01", accn="t"
                ),
                entry(
                    110,
                    2025,
                    start="2025-02-02",
                    end="2026-01-31",
                    filed="2026-03-01",
                    accn="t",
                    fy=2025,
                ),
            ]
        }
    )
    assert s.label(date(2025, 2, 1)) == "FY2024"
    assert s.label(date(2026, 1, 31)) == "FY2025"


def test_labels_follow_end_year_naming():
    # Walmart: the year ending 2026-01-31 is "fiscal 2026".
    s = resolve(
        {
            "Revenues": [
                entry(
                    110,
                    2025,
                    start="2025-02-01",
                    end="2026-01-31",
                    filed="2026-03-01",
                    accn="w",
                    fy=2026,
                ),
            ]
        }
    )
    assert s.label(date(2026, 1, 31)) == "FY2026"
    assert s.label(date(2025, 1, 31)) == "FY2025"


def test_predecessor_history_is_pooled():
    primary = companyfacts({"Revenues": [entry(200, 2016, accn="new")]}, cik=1)
    older = companyfacts({"Revenues": [entry(150, 2013, accn="old")]}, cik=2)
    revenue = edgar.statements(primary, predecessors=[older]).series("revenue")
    assert [f.cik for f in revenue.values()] == [2, 1]


def test_ticker_index():
    body = json.dumps({"0": {"cik_str": 1652044, "ticker": "googl", "title": "Alphabet Inc."}})
    assert edgar.ticker_index(body.encode())["GOOGL"] == (1652044, "Alphabet Inc.")


def test_capex_adds_capitalized_software_from_the_same_filing():
    s = resolve(
        {
            "PaymentsToAcquirePropertyPlantAndEquipment": [entry(489, 2025)],
            "PaymentsToAcquireSoftware": [entry(726, 2025)],
        }
    )
    capex = s.series("capex")[date(2025, 12, 31)]
    assert capex.value == 1215
    assert (
        capex.source_tag == "PaymentsToAcquirePropertyPlantAndEquipment + PaymentsToAcquireSoftware"
    )


def test_capex_software_sum_does_not_create_false_breaks():
    # Both 10-Ks agree on 2024. Comparing a PP&E-only "before" with a summed "after"
    # would wrongly report a basis change between 2023 and 2024.
    s = resolve(
        {
            "PaymentsToAcquirePropertyPlantAndEquipment": [
                entry(380, 2023, filed="2025-02-01", accn="a"),
                entry(474, 2024, filed="2025-02-01", accn="a"),
                entry(474, 2024, filed="2026-02-01", accn="b"),
                entry(489, 2025, filed="2026-02-01", accn="b"),
            ],
            "PaymentsToAcquireSoftware": [
                entry(600, 2023, filed="2025-02-01", accn="a"),
                entry(720, 2024, filed="2025-02-01", accn="a"),
                entry(720, 2024, filed="2026-02-01", accn="b"),
                entry(726, 2025, filed="2026-02-01", accn="b"),
            ],
        }
    )
    assert s.series("capex")[Y2024].value == 1194
    assert s.breaks == []


def test_combined_capex_tag_is_used_alone():
    s = resolve({"PaymentsToAcquireProductiveAssets": [entry(1273, 2025)]})
    capex = s.series("capex")[date(2025, 12, 31)]
    assert (capex.value, capex.source_tag) == (1273, "PaymentsToAcquireProductiveAssets")


DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"


def resolve_shares(tags):
    return edgar.statements(companyfacts(tags, unit="shares"))


def test_share_counts_read_only_the_shares_unit():
    s = resolve_shares({DILUTED: [entry(100, 2023)]})
    assert s.series("diluted_shares")[Y2023].unit == "shares"
    assert resolve({DILUTED: [entry(100, 2023)]}).series("diluted_shares") == {}


def test_stock_split_rescales_earlier_years():
    # The 2025 10-K restates 2023 after a 4:1 split; 2022 is only in the pre-split 10-K.
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(98, 2023, filed="2024-02-01", accn="a"),
                entry(392, 2023, filed="2025-02-01", accn="b"),
                entry(380, 2024, filed="2025-02-01", accn="b"),
            ]
        }
    )
    shares = s.series("diluted_shares")
    assert [f.value for f in shares.values()] == [400, 392, 380]
    assert (shares[Y2022].split_factor, shares[Y2022].as_reported) == (4, 100)
    assert shares[Y2023].split_factor == 1
    [split] = s.splits
    assert (split.end, split.ratio, split.before.value, split.after.value) == (Y2023, 4, 98, 392)
    assert s.breaks == []


def test_reverse_split_rescales_earlier_years():
    s = resolve_shares(
        {
            DILUTED: [
                entry(800, 2022, filed="2024-02-01", accn="a"),
                entry(784, 2023, filed="2024-02-01", accn="a"),
                entry(98, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.series("diluted_shares")[Y2022].value == 100
    assert s.splits[0].ratio == 1 / 8


def test_splits_compound():
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2021, filed="2023-02-01", accn="a"),
                entry(100, 2022, filed="2023-02-01", accn="a"),
                entry(200, 2022, filed="2024-02-01", accn="b"),
                entry(200, 2023, filed="2024-02-01", accn="b"),
                entry(600, 2023, filed="2025-02-01", accn="c"),
                entry(600, 2024, filed="2025-02-01", accn="c"),
            ]
        }
    )
    shares = s.series("diluted_shares")
    assert [f.value for f in shares.values()] == [600, 600, 600, 600]
    assert shares[Y2021].split_factor == 6


def test_split_factor_follows_the_filing_not_the_year():
    # The post-split 10-K tags 2021 and 2023 but not 2022, so 2022 comes from the
    # pre-split 10-K and still needs the 2:1 factor.
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2021, filed="2023-02-01", accn="a"),
                entry(100, 2022, filed="2023-02-01", accn="a"),
                entry(200, 2021, filed="2024-02-01", accn="b"),
                entry(200, 2023, filed="2024-02-01", accn="b"),
            ]
        }
    )
    assert [f.value for f in s.series("diluted_shares").values()] == [200, 200, 200]


def test_three_for_two_split():
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(100, 2023, filed="2024-02-01", accn="a"),
                entry(150, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.series("diluted_shares")[Y2022].value == 150
    assert s.splits[0].ratio == 1.5


@pytest.mark.parametrize("restated", [210, 7330])  # 2.1x and 73.3x are not split ratios
def test_ratios_that_are_not_stock_splits_stay_breaks(restated):
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(100, 2023, filed="2024-02-01", accn="a"),
                entry(restated, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.splits == []
    assert len(s.breaks) == 1


def test_stale_share_count_is_split_adjusted_and_hinted_in_shares():
    # The post-split 10-K presents 2021 (revenue) but tags its share count under another tag.
    hint = "WeightedAverageNumberOfDilutedSharesOutstandingRestated"
    facts = {
        DILUTED: {
            "units": {
                "shares": [
                    entry(100, 2021, filed="2023-02-01", accn="a"),
                    entry(100, 2022, filed="2023-02-01", accn="a"),
                    entry(400, 2022, filed="2024-02-01", accn="b"),
                ]
            }
        },
        hint: {"units": {"shares": [entry(400, 2021, filed="2024-02-01", accn="b")]}},
        "Revenues": {"units": {"USD": [entry(9, 2021, filed="2024-02-01", accn="b")]}},
    }
    body = json.dumps({"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": facts}})
    s = edgar.statements(body.encode())
    [stale] = [x for x in s.stale if x.concept == "diluted_shares"]
    assert stale.used.value == 400
    assert stale.hints == ((hint, 400.0),)


def test_basic_shares_differing_from_diluted_is_not_a_conflict():
    basic = "WeightedAverageNumberOfSharesOutstandingBasic"
    s = resolve_shares({DILUTED: [entry(102, 2023)], basic: [entry(100, 2023)]})
    assert s.series("diluted_shares")[Y2023].value == 102
    assert s.conflicts == []


def test_share_restatement_that_is_not_a_split_stays_a_break():
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(100, 2023, filed="2024-02-01", accn="a"),
                entry(130, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.splits == []
    assert len(s.breaks) == 1
    assert s.series("diluted_shares")[Y2022].value == 100


def test_scaling_errors_are_breaks_not_splits():
    # One 10-K tagged the count in thousands: a 1000x jump is not a stock split.
    s = resolve_shares(
        {
            DILUTED: [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(100, 2023, filed="2024-02-01", accn="a"),
                entry(100_000, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.splits == []
    assert len(s.breaks) == 1


def test_dollar_amounts_are_never_split_adjusted():
    s = resolve(
        {
            "Revenues": [
                entry(100, 2022, filed="2024-02-01", accn="a"),
                entry(100, 2023, filed="2024-02-01", accn="a"),
                entry(200, 2023, filed="2025-02-01", accn="b"),
            ]
        }
    )
    assert s.splits == []
    assert s.series("revenue")[Y2022].value == 100


@pytest.fixture
def balances(monkeypatch):
    """Balance-sheet concepts for these tests, until real ones are approved."""
    monkeypatch.setitem(edgar.CHAINS, "equity", ("StockholdersEquity",))
    monkeypatch.setitem(edgar.CHAINS, "cash", ("CashAndCashEquivalentsAtCarryingValue",))
    monkeypatch.setitem(edgar.HINTS, "equity", ("Equity",))
    monkeypatch.setitem(edgar.HINTS, "cash", ("Cash",))
    monkeypatch.setattr(edgar, "INSTANTS", frozenset({"equity", "cash"}))


def balance(val, end, filed, accn):
    return {"val": val, "end": end, "form": "10-K", "filed": filed, "accn": accn}


def test_year_end_balances_are_read(balances):
    s = resolve(
        {
            "Revenues": [entry(10, 2023, accn="a"), entry(9, 2022, filed="2024-02-01", accn="a")],
            "StockholdersEquity": [
                balance(70, "2023-12-31", "2024-02-01", "a"),
                balance(60, "2022-12-31", "2024-02-01", "a"),
            ],
        }
    )
    equity = s.series("equity")
    assert {end: f.value for end, f in equity.items()} == {Y2022: 60, Y2023: 70}
    assert equity[Y2023].period.days == 0


def test_balances_older_than_the_balance_sheet_are_ignored(balances):
    # The FY2023 10-K's equity statement repeats the 2021 year-end (restated to 51), but
    # only the FY2021 10-K's balance sheet shows it.
    s = resolve(
        {
            "Revenues": [
                entry(6, 2021, filed="2022-02-01", accn="a"),
                entry(8, 2023, filed="2024-02-01", accn="b"),
            ],
            "StockholdersEquity": [
                balance(50, "2021-12-31", "2022-02-01", "a"),
                balance(51, "2021-12-31", "2024-02-01", "b"),
                balance(70, "2023-12-31", "2024-02-01", "b"),
            ],
        }
    )
    assert s.series("equity")[Y2021].value == 50


def test_balances_off_a_fiscal_year_end_are_ignored(balances):
    s = resolve(
        {
            "Revenues": [entry(10, 2023)],
            "StockholdersEquity": [balance(70, "2023-06-30", "2024-02-01", "a")],
        }
    )
    assert s.series("equity") == {}


def test_a_three_year_income_statement_does_not_make_balances_stale(balances):
    # The FY2023 10-K shows 2021 revenue, but its balance sheet stops at 2022.
    s = resolve(
        {
            "Revenues": [
                entry(6, 2021, filed="2022-02-01", accn="a"),
                entry(6, 2021, filed="2024-02-01", accn="b"),
                entry(7, 2022, filed="2024-02-01", accn="b"),
                entry(8, 2023, filed="2024-02-01", accn="b"),
            ],
            "StockholdersEquity": [
                balance(50, "2021-12-31", "2022-02-01", "a"),
                balance(60, "2022-12-31", "2024-02-01", "b"),
                balance(70, "2023-12-31", "2024-02-01", "b"),
            ],
        }
    )
    assert s.series("equity")[Y2021].value == 50
    assert [x for x in s.stale if x.concept == "equity"] == []


def test_stale_balance_is_flagged_with_hints(balances):
    # The FY2023 10-K's balance sheet shows 2022 (cash), but tags equity under another tag.
    hint = "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    s = resolve(
        {
            "Revenues": [
                entry(7, 2022, filed="2023-02-01", accn="a"),
                entry(8, 2023, filed="2024-02-01", accn="b"),
            ],
            "StockholdersEquity": [
                balance(60, "2022-12-31", "2023-02-01", "a"),
                balance(70, "2023-12-31", "2024-02-01", "b"),
            ],
            "CashAndCashEquivalentsAtCarryingValue": [
                balance(5, "2022-12-31", "2024-02-01", "b"),
                balance(6, "2023-12-31", "2024-02-01", "b"),
            ],
            hint: [balance(61, "2022-12-31", "2024-02-01", "b")],
        }
    )
    [stale] = [x for x in s.stale if x.concept == "equity"]
    assert (stale.end, stale.used.value, stale.newer_accession) == (Y2022, 60, "b")
    assert stale.hints == ((hint, 61.0),)


# Debt and cash are summed from one filing's tags (DECISIONS #60, #61). Values in $B.


def debt(**found):
    tags, problems = edgar._debt(found)
    return tags, sum(found[t] for t in tags), problems


def test_debt_adds_components_and_both_lease_halves():  # WMT
    tags, total, problems = debt(
        ShortTermBorrowings=6.6,
        LongTermDebtCurrent=3.5,
        LongTermDebtNoncurrent=34.6,
        FinanceLeaseLiabilityCurrent=0.9,
        FinanceLeaseLiabilityNoncurrent=5.9,
        FinanceLeaseLiability=6.8,
    )
    assert total == pytest.approx(51.5)
    assert "FinanceLeaseLiability" not in tags
    assert problems == []


def test_debt_skips_leases_already_inside_the_debt_lines():  # TGT
    tags, total, _ = debt(
        LongTermDebtAndCapitalLeaseObligationsCurrent=2.1,
        LongTermDebtAndCapitalLeaseObligations=14.3,
        FinanceLeaseLiabilityCurrent=0.1,
        FinanceLeaseLiabilityNoncurrent=2.0,
    )
    assert total == pytest.approx(16.4)


def test_debt_sees_leases_inside_when_the_inclusive_tag_has_the_same_value():  # XOM
    tags, total, problems = debt(
        CommercialPaper=3.1,
        LongTermDebtCurrent=6.2,
        LongTermDebtAndCapitalLeaseObligationsCurrent=6.2,
        LongTermDebtAndCapitalLeaseObligations=34.2,
        FinanceLeaseLiability=2.7,
        DebtCurrent=9.3,
    )
    assert tags == [
        "CommercialPaper",
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ]
    assert problems == []


def test_short_term_borrowings_plus_commercial_paper_when_that_ties_out():  # NEE
    tags, total, problems = debt(
        ShortTermBorrowings=1e9, CommercialPaper=2e9, LongTermDebtCurrent=3e9, DebtCurrent=6e9
    )
    assert (total, problems) == (6e9, [])


def test_short_term_borrowings_alone_when_they_include_commercial_paper():  # KO 2019-22
    tags, total, problems = debt(
        ShortTermBorrowings=3e9, CommercialPaper=2e9, LongTermDebtCurrent=1e9, DebtCurrent=4e9
    )
    assert (total, problems) == (4e9, [])


def test_current_debt_total_is_used_only_without_components():
    tags, total, _ = debt(DebtCurrent=5, LongTermDebtNoncurrent=20)
    assert (tags, total) == (["DebtCurrent", "LongTermDebtNoncurrent"], 25)


def test_lease_total_is_added_when_no_debt_line_includes_leases():
    _, total, problems = debt(
        LongTermDebtCurrent=1, LongTermDebtNoncurrent=10, FinanceLeaseLiability=2
    )
    assert (total, problems) == (13, [])


def test_lease_total_is_flagged_when_part_may_be_inside():
    _, total, [problem] = debt(
        LongTermDebtCurrent=1e9,
        LongTermDebtAndCapitalLeaseObligations=10e9,
        FinanceLeaseLiability=2e9,
    )
    assert total == 11e9
    assert problem.startswith("Finance leases ($2.0B) are reported only as a total")


def test_debt_that_misses_the_filings_own_total_is_flagged():
    _, _, [problem] = debt(
        LongTermDebtCurrent=1e9,
        LongTermDebtNoncurrent=10e9,
        DebtLongtermAndShorttermCombinedAmount=15e9,
    )
    assert "DebtLongtermAndShorttermCombinedAmount is $15.0B" in problem
    assert "come to $11.0B" in problem


def cash(**found):
    tags, problems = edgar._cash(found)
    return tags, sum(found[t] for t in tags), problems


def test_cash_uses_the_filings_total_when_the_parts_add_up():  # MSFT
    tags, total, problems = cash(
        CashCashEquivalentsAndShortTermInvestments=76.8,
        CashAndCashEquivalentsAtCarryingValue=20.9,
        ShortTermInvestments=55.9,
    )
    assert (tags, total, problems) == (["CashCashEquivalentsAndShortTermInvestments"], 76.8, [])


def test_marketable_securities_outside_the_total_are_added():  # KO
    tags, total, problems = cash(
        CashCashEquivalentsAndShortTermInvestments=10,
        CashAndCashEquivalentsAtCarryingValue=8,
        OtherShortTermInvestments=2,
        MarketableSecurities=1,
    )
    assert tags == ["CashCashEquivalentsAndShortTermInvestments", "MarketableSecurities"]
    assert (total, problems) == (11, [])


def test_short_term_investments_inside_cash_are_not_added_again():  # TGT
    tags, total, problems = cash(
        CashCashEquivalentsAndShortTermInvestments=5.5e9,
        CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents=5.5e9,
        ShortTermInvestments=4.6e9,
    )
    assert (total, problems) == (5.5e9, [])


def test_a_total_that_doesnt_match_its_parts_wins_and_is_flagged():
    tags, total, [problem] = cash(
        CashCashEquivalentsAndShortTermInvestments=7e9,
        CashAndCashEquivalentsAtCarryingValue=5e9,
        ShortTermInvestments=4e9,
    )
    assert total == 7e9
    assert "doesn't match its parts ($9.0B)" in problem


def test_cash_parts_are_summed_without_a_total():  # AAPL
    tags, total, problems = cash(
        CashAndCashEquivalentsAtCarryingValue=35.9, MarketableSecuritiesCurrent=18.8
    )
    assert (total, problems) == (pytest.approx(54.7), [])


def test_marketable_securities_that_may_be_long_term_are_flagged_not_counted():
    tags, total, [problem] = cash(
        CashAndCashEquivalentsAtCarryingValue=5e9,
        MarketableSecurities=9e9,
        MarketableSecuritiesCurrent=3e9,
        MarketableSecuritiesNoncurrent=6e9,
    )
    assert total == 8e9
    assert problem.startswith("MarketableSecurities ($9.0B) isn't counted")


def test_a_second_short_term_investment_line_without_a_total_is_flagged():
    tags, total, [problem] = cash(
        CashAndCashEquivalentsAtCarryingValue=5e9,
        ShortTermInvestments=3e9,
        MarketableSecuritiesCurrent=2e9,
    )
    assert total == 8e9
    assert (
        problem
        == "MarketableSecuritiesCurrent ($2.0B) isn't counted; only ShortTermInvestments is."
    )


def test_summed_balances_resolve_with_their_flags():
    s = resolve(
        {
            "Revenues": [entry(10, 2023, filed="2024-02-01", accn="a")],
            "LongTermDebtCurrent": [balance(1e9, "2023-12-31", "2024-02-01", "a")],
            "LongTermDebtNoncurrent": [balance(10e9, "2023-12-31", "2024-02-01", "a")],
            "DebtLongtermAndShorttermCombinedAmount": [
                balance(15e9, "2023-12-31", "2024-02-01", "a")
            ],
        }
    )
    fact = s.series("debt")[Y2023]
    assert (fact.value, fact.source_tag) == (11e9, "LongTermDebtCurrent + LongTermDebtNoncurrent")
    assert [f.concept for f in s.flags] == ["debt"]
    assert s.conflicts == []


def test_redeemable_nci_outside_equity_is_added():  # MA 2023
    tags, problems = edgar._equity(
        {
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": 6.0,
            "StockholdersEquity": 5.9,
            "RedeemableNoncontrollingInterestEquityFairValue": 0.1,
        }
    )
    assert tags == [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "RedeemableNoncontrollingInterestEquityFairValue",
    ]


def test_a_held_for_sale_business_flags_the_year():  # KO 2025
    _, _, [problem] = debt(
        LongTermDebtNoncurrent=40e9, LiabilitiesOfDisposalGroupIncludingDiscontinuedOperation=5e9
    )
    assert problem.startswith("Part of the business is held for sale or discontinued")


def test_plain_investments_count_when_they_fit_in_current_assets():  # MA
    tags, total, problems = cash(
        CashAndCashEquivalentsAtCarryingValue=9e9, Investments=0.3e9, AssetsCurrent=25e9
    )
    assert (total, problems) == (9.3e9, [])


@pytest.mark.parametrize(
    "found",
    [
        # An insurer's whole portfolio, next to a short-term line (PGR)
        {"ShortTermInvestments": 2e9, "Investments": 90e9, "AssetsCurrent": 100e9},
        # An unclassified balance sheet (GE before 2019)
        {"Investments": 40e9},
        # Bigger than current assets can hold
        {"Investments": 30e9, "AssetsCurrent": 25e9},
    ],
)
def test_plain_investments_are_flagged_not_counted_otherwise(found):
    tags, total, [problem] = cash(CashAndCashEquivalentsAtCarryingValue=1e9, **found)
    assert "Investments" not in tags
    assert problem.startswith("Investments (")
