"""
Compliance: PDT rules, account constraints, best execution note.

- Pattern Day Trader (PDT): margin account day-trading may require $25,000 min equity.
- FINRA has discussed modernizing/eliminating the $25k PDT; treat as current but potentially changing.
- Broker best execution duty (enforced via app limits only).
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass
class PDTState:
    equity: float
    day_trades_count_rolling: int
    day_trade_dates: list[date]  # last 5 business days of day-trades


class ComplianceManager:
    """
    Enforces PDT: if margin account and day-trading, require min equity and limit day-trades
    when below threshold.
    """

    def __init__(self, config: dict[str, Any]):
        comp = config.get("compliance", {})
        self.pdt_min_equity = float(comp.get("pdt_min_equity", 25_000))
        self.pdt_enabled = bool(comp.get("pdt_enabled", True))
        self.margin_account = bool(comp.get("margin_account", True))
        self.best_execution_note = str(comp.get("best_execution_note", ""))

    def can_day_trade(self, state: PDTState, trade_date: date) -> tuple[bool, str]:
        """
        PDT: In a margin account, if you make 4+ day trades in 5 business days and
        equity < $25k, you get flagged. Many brokers block further day trades.
        So: if equity < 25k, allow at most 3 day trades in rolling 5 business days.
        """
        if not self.pdt_enabled or not self.margin_account:
            return True, "PDT not applicable"

        if state.equity >= self.pdt_min_equity:
            return True, "equity above PDT threshold"

        # Below $25k: restrict to 3 day trades in rolling 5 business days
        max_day_trades_below_threshold = 3
        # Prune to last 5 business days
        cutoff = trade_date - timedelta(days=7)  # safe window to include 5 biz days
        recent = [d for d in state.day_trade_dates if d >= cutoff]
        if len(recent) >= max_day_trades_below_threshold:
            return False, (
                f"PDT: equity ${state.equity:,.0f} < ${self.pdt_min_equity:,.0f}; "
                f"day trade limit ({max_day_trades_below_threshold}) in rolling 5 business days reached"
            )
        return True, "ok"

    def record_day_trade(self, state: PDTState, trade_date: date) -> None:
        state.day_trade_dates.append(trade_date)
        # Keep only last 5 business days (simplified: keep last 10 dates then filter when checking)
        if len(state.day_trade_dates) > 20:
            state.day_trade_dates = state.day_trade_dates[-20:]

    def update_equity(self, state: PDTState, equity: float) -> None:
        state.equity = equity
