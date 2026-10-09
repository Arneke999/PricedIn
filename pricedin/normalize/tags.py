"""Ordered XBRL tag fallback chains per canonical concept.

Approved by Arne after the Phase 0b spike (DECISIONS #31-#34), SBC and diluted shares
in Phase 1 (#49, #52). For each fiscal year the
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
    "sbc": (
        # The cash-flow add-back only (DECISIONS #52): FCF minus SBC subtracts what operating
        # cash flow added back. The expense tag measures something else, and GE files its
        # after-tax figure under it.
        "ShareBasedCompensation",
    ),
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        # Filers with no dilutive securities may tag only basic (XOM after 2013)
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}

# Fallback tags that measure something narrower than the concept: a different value in the
# same filing is expected, not a conflict.
NARROWER: dict[str, frozenset[str]] = {
    "diluted_shares": frozenset({"WeightedAverageNumberOfSharesOutstandingBasic"}),
}

# companyfacts unit per concept; concepts not listed are in USD.
UNITS: dict[str, str] = {"diluted_shares": "shares"}

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
    "sbc": ("ShareBased", "StockBased"),
    "diluted_shares": ("WeightedAverageNumber",),
}
