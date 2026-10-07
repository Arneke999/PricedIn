"""Ordered XBRL tag fallback chains per canonical concept.

For each period, the first tag in the chain that has a value wins. Later tags that
report a different value for the same period are recorded as conflicts.

PROVISIONAL (Phase 0a skeleton). The fallback order for every concept is Arne's decision
(CLAUDE.md) and these orders are not yet approved. The revenue chain is the one from the
original roadmap; the others are the obvious us-gaap tags. Phase 1 replaces this file with
chains seeded from edgartools' gaap_mappings.json (MIT).
"""

CHAINS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}
