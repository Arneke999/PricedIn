"""Cash flow metrics.

Golden-tested (tests/golden). A page charts them only through metrics/verified.py.
"""

from __future__ import annotations

from datetime import date

from pricedin.normalize.schema import Fact


def free_cash_flow(
    operating_cash_flow: dict[date, Fact], capex: dict[date, Fact]
) -> dict[date, float]:
    """Operating cash flow (continuing operations first, DECISIONS #34) minus capital
    expenditure.

    SBC is not deducted here; see free_cash_flow_after_sbc (DECISIONS #58).
    capex is reported as a positive payment, so it is subtracted.
    """
    ends = sorted(operating_cash_flow.keys() & capex.keys())
    return {e: operating_cash_flow[e].value - capex[e].value for e in ends}


def free_cash_flow_after_sbc(
    operating_cash_flow: dict[date, Fact], capex: dict[date, Fact], sbc: dict[date, Fact]
) -> dict[date, float]:
    """Free cash flow minus stock-based compensation (DECISIONS #58): the SBC that operating
    cash flow added back (#52) is a real cost to shareholders. Years without SBC are left
    out rather than treated as zero."""
    fcf = free_cash_flow(operating_cash_flow, capex)
    return {e: fcf[e] - sbc[e].value for e in fcf if e in sbc}
