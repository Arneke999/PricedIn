"""Cash flow metrics.

Phase 0a skeleton: no golden test yet, so these render only under the page-wide
"unverified" banner (DECISIONS #17).
"""

from __future__ import annotations

from datetime import date

from pricedin.normalize.schema import Fact


def free_cash_flow(
    operating_cash_flow: dict[date, Fact], capex: dict[date, Fact]
) -> dict[date, float]:
    """Operating cash flow (continuing operations first, DECISIONS #34) minus capital
    expenditure.

    SBC is not deducted. Whether and how to deduct it is still Arne's open decision.
    capex is reported as a positive payment, so it is subtracted.
    """
    ends = sorted(operating_cash_flow.keys() & capex.keys())
    return {e: operating_cash_flow[e].value - capex[e].value for e in ends}
