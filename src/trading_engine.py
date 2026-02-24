"""
Trading engine: orchestrates universe, strategy, sizing, portfolio risk, execution, compliance.

Runs the full gate sequence before any trade and applies all rules.
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from .config_loader import load_config
from .universe import MarketCalendar, UniverseFilter, MarketQualityGate, MarketQualityResult
from .strategy import TrendFollowingStrategy, EntrySignal, ExitSignal
from .position_sizing import PositionSizer, PositionSizingResult
from .portfolio_risk import PortfolioRiskManager, PortfolioRiskState
from .execution import ExecutionManager, ExecutionState
from .compliance import ComplianceManager, PDTState
from .trade_filters import MacroEventBlackout, EarningsBlackout, VolatilityDoNotTrade


@dataclass
class TradingEngineState:
    portfolio_risk: PortfolioRiskState = field(default_factory=PortfolioRiskState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    pdt: PDTState = field(default_factory=lambda: PDTState(equity=0.0, day_trades_count_rolling=0, day_trade_dates=[]))


@dataclass
class TradeDecision:
    allowed: bool
    reason: str
    order_request: Any = None
    entry_signal: EntrySignal | None = None
    position_sizing: PositionSizingResult | None = None


class TradingEngine:
    """
    Single place to run all gates before sending a order.
    """

    def __init__(self, config: dict[str, Any] | None = None, config_path: str | Path | None = None):
        self.config = config or load_config(config_path)
        self.calendar = MarketCalendar(self.config)
        self.universe = UniverseFilter(self.config)
        self.market_quality = MarketQualityGate(self.config)
        self.strategy = TrendFollowingStrategy(self.config)
        self.sizer = PositionSizer(self.config)
        self.portfolio_risk = PortfolioRiskManager(self.config)
        self.execution = ExecutionManager(self.config)
        self.compliance = ComplianceManager(self.config)
        self.macro_blackout = MacroEventBlackout(self.config)
        self.earnings_blackout = EarningsBlackout(self.config)
        self.volatility_dnt = VolatilityDoNotTrade(self.config)
        self.state = TradingEngineState()

    def update_equity(self, equity: float, dt: datetime | None = None) -> None:
        dt = dt or datetime.utcnow()
        self.state.portfolio_risk.peak_equity = max(
            self.state.portfolio_risk.peak_equity,
            equity,
        )
        self.portfolio_risk.update_equity(self.state.portfolio_risk, dt, equity)
        self.compliance.update_equity(self.state.pdt, equity)

    def is_trading_allowed(self, dt: datetime) -> bool:
        return self.calendar.is_trading_allowed(dt)

    def run_entry_gates(
        self,
        symbol: str,
        dt: datetime,
        account_equity: float,
        current_positions: dict[str, Any],
        sector_exposure_pct: dict[str, float],
        # Market data for quality & strategy
        spread_pct: float,
        volume_atr_ratio: float | None = None,
        atr_multiple: float | None = None,
        ohlcv_df: Any = None,
        symbol_sector: dict[str, str] | None = None,
    ) -> TradeDecision:
        """
        Run full gate sequence for an entry. Returns TradeDecision with allowed=False
        and reason if any gate fails.
        """
        today = dt.date() if isinstance(dt, datetime) else date.today()

        if not self.calendar.is_trading_allowed(dt):
            return TradeDecision(allowed=False, reason="market closed or session not tradeable")

        macro = self.macro_blackout.check(dt)
        if not macro.allowed:
            return TradeDecision(allowed=False, reason=macro.reason)

        if not self.universe.is_eligible(symbol):
            return TradeDecision(allowed=False, reason=f"symbol {symbol} not in universe or liquidity filter")

        earnings = self.earnings_blackout.check(symbol, dt)
        if not earnings.allowed:
            return TradeDecision(allowed=False, reason=earnings.reason)

        mq = self.market_quality.check(
            spread_pct=spread_pct,
            volume_atr_ratio=volume_atr_ratio,
            current_atr_multiple=atr_multiple,
        )
        if not mq.ok:
            return TradeDecision(allowed=False, reason=f"market_quality: {mq.reason}")

        allowed, reason = self.execution.can_trade_spread(spread_pct)
        if not allowed:
            return TradeDecision(allowed=False, reason=reason)

        vol_dnt = self.volatility_dnt.check(atr_pct=atr_multiple, spread_pct=spread_pct)
        if not vol_dnt.allowed:
            return TradeDecision(allowed=False, reason=vol_dnt.reason)

        if self.execution.should_block_strategy(self.state.execution):
            return TradeDecision(
                allowed=False,
                reason="strategy blocked: avg slippage exceeded threshold",
            )

        can_trade, reason = self.portfolio_risk.can_trade(
            self.state.portfolio_risk,
            account_equity,
            symbol,
            today,
        )
        if not can_trade:
            return TradeDecision(allowed=False, reason=reason)

        can_dt, reason = self.compliance.can_day_trade(self.state.pdt, today)
        if not can_dt:
            return TradeDecision(allowed=False, reason=reason)

        entry = self.strategy.generate_entry(symbol, ohlcv_df, spread_pct, atr_multiple)
        if entry is None:
            return TradeDecision(allowed=False, reason="no entry signal")

        # Position sizing
        current_with_stops = [
            (p.get("notional", 0), p.get("stop_pct", 0))
            for p in current_positions.values()
        ]
        open_risk_pct = self.sizer.total_open_risk_pct(account_equity, current_with_stops)
        sizing = self.sizer.size_position(
            account_equity=account_equity,
            price=ohlcv_df["close"].iloc[-1] if ohlcv_df is not None and not ohlcv_df.empty else 0.0,
            stop_distance_pct=entry.stop_pct,
            symbol=symbol,
            current_positions=current_positions,
            sector_exposure_pct=sector_exposure_pct,
            symbol_sector=symbol_sector,
            atr_pct=atr_multiple,
        )
        if sizing.reject_reason:
            return TradeDecision(
                allowed=False,
                reason=sizing.reject_reason,
                entry_signal=entry,
            )
        if self.sizer.would_exceed_max_open_risk(open_risk_pct, entry.stop_pct, sizing.risk_pct):
            return TradeDecision(
                allowed=False,
                reason=f"would exceed max open risk ({self.sizer.max_open_risk_pct}%)",
                entry_signal=entry,
                position_sizing=sizing,
            )

        # Build order (limit preferred)
        mid = ohlcv_df["close"].iloc[-1] if ohlcv_df is not None and not ohlcv_df.empty else 0.0
        order = self.execution.build_order(
            symbol=symbol,
            side=entry.side,
            quantity=sizing.shares,
            mid_price=mid,
            spread_pct=spread_pct,
        )
        if order is None:
            return TradeDecision(
                allowed=False,
                reason="execution: order build failed (spread?)",
                entry_signal=entry,
                position_sizing=sizing,
            )

        return TradeDecision(
            allowed=True,
            reason="ok",
            order_request=order,
            entry_signal=entry,
            position_sizing=sizing,
        )

    def check_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        bars_held: int,
        spread_pct: float | None = None,
        atr_multiple: float | None = None,
    ) -> ExitSignal | None:
        return self.strategy.check_exit(
            symbol, entry_price, current_price, bars_held, spread_pct, atr_multiple
        )
