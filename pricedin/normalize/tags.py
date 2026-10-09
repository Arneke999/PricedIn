"""Ordered XBRL tag fallback chains per canonical concept.

Approved by Arne after the Phase 0b spike (DECISIONS #31-#34), SBC and diluted shares
in Phase 1 (#49, #52). For each fiscal year the
newest filing wins, then the first tag in the chain that the filing reports. Changing an
order is Arne's decision. edgartools' MIT gaap_mappings.json is a reading reference when
extending a chain.
"""

# Debt is summed from components within one filing, and tied out against the filing's own
# totals (DECISIONS #60). Short-term borrowings: ShortTermBorrowings, else its parts.
SHORT_TERM_BORROWINGS = "ShortTermBorrowings"
SHORT_TERM_BORROWING_PARTS = ("CommercialPaper", "OtherShortTermBorrowings")
CURRENT_LONG_TERM_DEBT = ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent")
NONCURRENT_LONG_TERM_DEBT = ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations")
# All current debt in one number: used only when a filing reports no short-term component.
DEBT_CURRENT = "DebtCurrent"
# Debt tags whose value already includes finance (formerly capital) leases.
INCLUDES_LEASES = frozenset(
    {"LongTermDebtAndCapitalLeaseObligationsCurrent", "LongTermDebtAndCapitalLeaseObligations"}
)
FINANCE_LEASES_CURRENT = ("FinanceLeaseLiabilityCurrent", "CapitalLeaseObligationsCurrent")
FINANCE_LEASES_NONCURRENT = ("FinanceLeaseLiabilityNoncurrent", "CapitalLeaseObligationsNoncurrent")
FINANCE_LEASES_TOTAL = ("FinanceLeaseLiability", "CapitalLeaseObligations")
# The filing's own totals: all debt, and long-term debt including its current part.
DEBT_TOTAL = "DebtLongtermAndShorttermCombinedAmount"
LONG_TERM_DEBT_TOTAL = "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
# A business held for sale or discontinued: its debt and cash sit outside the lines read
# (DECISIONS #66), so the year gets a warning.
DISPOSAL_GROUP_LIABILITIES = "LiabilitiesOfDisposalGroupIncludingDiscontinuedOperation"

# Equity including minority holders (#59), plus redeemable NCI outside equity (#65).
EQUITY = (
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
)
REDEEMABLE_NCI = (
    "RedeemableNoncontrollingInterestEquityCarryingAmount",
    "RedeemableNoncontrollingInterestEquityFairValue",
)

# Cash and short-term investments (DECISIONS #54, #61). When the filing reports its own
# total, that total is used, reconciled against the parts; otherwise the parts are summed.
CASH_AND_INVESTMENTS_TOTAL = "CashCashEquivalentsAndShortTermInvestments"
CASH = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
# One balance-sheet line, first found.
SHORT_TERM_INVESTMENTS = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "AvailableForSaleSecuritiesCurrent",
)
OTHER_SHORT_TERM_INVESTMENTS = "OtherShortTermInvestments"  # its own line, added
# Counted as current only when the filing tags no current/noncurrent split (KO).
MARKETABLE_SECURITIES = "MarketableSecurities"
MARKETABLE_SPLIT = ("MarketableSecuritiesCurrent", "MarketableSecuritiesNoncurrent")
# Plain "Investments" counts as short-term only when the filing classifies its balance sheet,
# tags no short/long split, and the line fits in current assets (MA, not insurers).
INVESTMENTS = "Investments"
INVESTMENT_SPLITS = (
    "ShortTermInvestments",
    "LongTermInvestments",
    "InvestmentsNoncurrent",
    "OtherLongTermInvestments",
)
ASSETS_CURRENT = "AssetsCurrent"
MARKETABLE_LINES = frozenset({MARKETABLE_SECURITIES, INVESTMENTS, *SHORT_TERM_INVESTMENTS[1:]})

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
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "equity": (*EQUITY, *REDEEMABLE_NCI),
    # Summed concepts list every tag they read; the order doesn't rank them.
    "debt": (
        SHORT_TERM_BORROWINGS,
        *SHORT_TERM_BORROWING_PARTS,
        *CURRENT_LONG_TERM_DEBT,
        *NONCURRENT_LONG_TERM_DEBT,
        DEBT_CURRENT,
        *FINANCE_LEASES_CURRENT,
        *FINANCE_LEASES_NONCURRENT,
        *FINANCE_LEASES_TOTAL,
        DEBT_TOTAL,
        LONG_TERM_DEBT_TOTAL,
        DISPOSAL_GROUP_LIABILITIES,
    ),
    "cash_and_short_term_investments": (
        CASH_AND_INVESTMENTS_TOTAL,
        *CASH,
        *SHORT_TERM_INVESTMENTS,
        OTHER_SHORT_TERM_INVESTMENTS,
        MARKETABLE_SECURITIES,
        "MarketableSecuritiesNoncurrent",
        INVESTMENTS,
        *INVESTMENT_SPLITS[1:],
        ASSETS_CURRENT,
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

# Concepts measured at a fiscal-year end (balance sheet) rather than over the year.
INSTANTS = frozenset({"equity", "debt", "cash_and_short_term_investments"})
# Concepts summed from several tags in one filing rather than picked from a chain.
SUMMED = frozenset({"equity", "debt", "cash_and_short_term_investments"})

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
    "income_tax": ("IncomeTax",),
    "pretax_income": ("BeforeIncomeTaxes",),
    "equity": ("StockholdersEquity",),
    "debt": ("Debt", "Borrowings", "CommercialPaper"),
    "cash_and_short_term_investments": ("Cash", "ShortTermInvestments", "MarketableSecurities"),
}
