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
