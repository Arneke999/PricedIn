"""The discount rate: a required return, not a CAPM WACC (DECISIONS #69).

Required return = the 10-year Treasury yield + an equity risk premium, 5% by default and
editable per company in the calculator (Phase 3).
"""

from __future__ import annotations

EQUITY_RISK_PREMIUM = 0.05


def required_return(ten_year_yield: float, premium: float = EQUITY_RISK_PREMIUM) -> float:
    return ten_year_yield + premium
