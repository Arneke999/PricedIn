"""Cash flow metrics.

Phase 0a skeleton: no golden test yet, so these render only under the page-wide
"unverified" banner (DECISIONS #17).
"""

from __future__ import annotations

from pricedin.normalize.schema import Fact, Period


def free_cash_flow(
    operating_cash_flow: dict[Period, Fact], capex: dict[Period, Fact]
) -> dict[Period, float]:
    """Operating cash flow minus capital expenditure.

    SBC is not deducted. Whether and how to deduct it is still Arne's open decision.
    capex is reported as a positive payment, so it is subtracted.
    """
    periods = sorted(operating_cash_flow.keys() & capex.keys())
    return {p: operating_cash_flow[p].value - capex[p].value for p in periods}
