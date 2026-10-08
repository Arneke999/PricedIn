"""Ordered XBRL tag fallback chains per canonical concept.

Approved by Arne after the Phase 0b spike (DECISIONS #31-#34). For each fiscal year the
newest filing wins, then the first tag in the chain that the filing reports. Changing an
order is Arne's decision. edgartools' MIT gaap_mappings.json is a reading reference when
extending a chain.
"""

CHAINS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RegulatedAndUnregulatedOperatingRevenue",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "operating_income": (
        "OperatingIncomeLoss",
        # EBIT, for filers that present it instead of operating income (Target)
        "IncomeLossFromContinuingOperationsBeforeInterestExpenseInterestIncomeIncomeTaxesExtraordinaryItemsNoncontrollingInterestsNet",
    ),
    "net_income": (
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInOperatingActivities",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}

# Capitalized software is added to PP&E capex when the same filing reports both for the same
# year (DECISIONS #40, #41). First tag found wins.
CAPEX_PPE = "PaymentsToAcquirePropertyPlantAndEquipment"
CAPEX_SOFTWARE = ("PaymentsToAcquireSoftware", "PaymentsToDevelopSoftware")

# ASC 606 contract revenue can exclude lease, interest or insurance income. When the
# filing also reports this tag, contract revenue is likely a subset of the total.
NON_CONTRACT_REVENUE = "RevenueNotFromContractWithCustomer"
CONTRACT_REVENUE = frozenset(
    {
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    }
)

# Name fragments used to suggest which tag a newer filing used instead (stale values).
HINTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenue", "Sales"),
    "operating_income": ("OperatingIncome", "BeforeInterest"),
    "net_income": ("NetIncome", "ProfitLoss"),
    "operating_cash_flow": ("OperatingActivities",),
    "capex": ("PaymentsToAcquire",),
}
