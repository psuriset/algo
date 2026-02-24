"""
Portfolio & drawdown controls: daily loss limit, max drawdown, safe mode, trade frequency.

- Daily loss limit: e.g. -1% to -3% → stop trading for the day.
- Max drawdown: e.g. -10% → safe mode (paper only) until recovery.
- Trade frequency limit to prevent overtrading loops.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class PortfolioRiskState:
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    peak_equity: float = 0.0
    daily_pnl_pct: float = 0.0
    daily_trade_count: int = 0
    daily_trades_per_symbol: dict[str, int] = field(default_factory=dict)
    last_trade_date: date | None = None
    safe_mode: bool = False
    trading_stopped_for_day: bool = False


class PortfolioRiskManager:
    def __init__(self, config: dict[str, Any]):
        pr = config.get("portfolio_risk", {})
        self.daily_loss_limit_pct = float(pr.get("daily_loss_limit_pct", -2.0))
        self.max_drawdown_pct = float(pr.get("max_drawdown_pct", -10.0))
        self.safe_mode_after_max_dd = bool(pr.get("safe_mode_after_max_dd", True))
        self.recovery_criteria_pct = float(pr.get("recovery_criteria_pct", -8.0))
        self.max_trades_per_day = int(pr.get("max_trades_per_day", 15))
        self.max_trades_per_symbol_per_day = int(pr.get("max_trades_per_symbol_per_day", 3))

    def update_equity(self, state: PortfolioRiskState, dt: datetime, equity: float) -> None:
        state.equity_curve.append((dt, equity))
        if equity > state.peak_equity:
            state.peak_equity = equity

    def current_drawdown_pct(self, state: PortfolioRiskState, current_equity: float) -> float:
        if state.peak_equity <= 0:
            return 0.0
        return ((current_equity - state.peak_equity) / state.peak_equity) * 100.0

    def check_daily_reset(self, state: PortfolioRiskState, today: date) -> None:
        if state.last_trade_date != today:
            state.daily_pnl_pct = 0.0
            state.daily_trade_count = 0
            state.daily_trades_per_symbol = {}
            state.trading_stopped_for_day = False
            state.last_trade_date = today

    def can_trade(
        self,
        state: PortfolioRiskState,
        current_equity: float,
        symbol: str,
        today: date | None = None,
    ) -> tuple[bool, str]:
        """
        Returns (allowed, reason). If not allowed, reason explains why.
        """
        if today is None:
            today = date.today()
        self.check_daily_reset(state, today)

        if state.safe_mode:
            dd = self.current_drawdown_pct(state, current_equity)
            if dd <= self.recovery_criteria_pct:
                return False, f"safe_mode: drawdown {dd:.2f}% not yet recovered to {self.recovery_criteria_pct}%"
            # Optionally clear safe_mode when recovered (implementation can flip state.safe_mode here)

        if state.trading_stopped_for_day:
            return False, "daily loss limit hit; trading stopped for the day"

        if state.daily_pnl_pct <= self.daily_loss_limit_pct:
            state.trading_stopped_for_day = True
            return False, f"daily loss limit {self.daily_loss_limit_pct}% hit (current: {state.daily_pnl_pct:.2f}%)"

        dd_pct = self.current_drawdown_pct(state, current_equity)
        if dd_pct <= self.max_drawdown_pct and self.safe_mode_after_max_dd:
            state.safe_mode = True
            return False, f"max drawdown {self.max_drawdown_pct}% hit; entering safe mode"

        if state.daily_trade_count >= self.max_trades_per_day:
            return False, f"max trades per day ({self.max_trades_per_day}) reached"

        sym_count = state.daily_trades_per_symbol.get(symbol, 0)
        if sym_count >= self.max_trades_per_symbol_per_day:
            return False, f"max trades per symbol per day ({self.max_trades_per_symbol_per_day}) for {symbol}"

        return True, "ok"

    def record_trade(self, state: PortfolioRiskState, symbol: str, pnl_pct: float) -> None:
        state.daily_trade_count += 1
        state.daily_trades_per_symbol[symbol] = state.daily_trades_per_symbol.get(symbol, 0) + 1
        state.daily_pnl_pct += pnl_pct
