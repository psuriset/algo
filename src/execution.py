"""
Execution rules: limit orders in liquid names, spread gate, partial fills, slippage tracking.

- Prefer limit orders; avoid market in thin books.
- Don't trade if spread too wide.
- Handle partial fills + cancel/replace logic.
- Track expected vs actual fill (slippage); block strategies that degrade.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: OrderType
    limit_price: float | None = None
    expected_price: float | None = None


@dataclass
class FillReport:
    symbol: str
    side: str
    quantity: int
    fill_price: float
    expected_price: float
    slippage_bps: float
    timestamp: datetime


@dataclass
class ExecutionState:
    fill_history: list[FillReport] = field(default_factory=list)
    strategy_slippage_bps_avg: float = 0.0
    strategy_blocked: bool = False


class ExecutionManager:
    def __init__(self, config: dict[str, Any]):
        ex = config.get("execution", {})
        self.prefer_limit_orders = bool(ex.get("prefer_limit_orders", True))
        self.limit_order_offset_ticks = int(ex.get("limit_order_offset_ticks", 1))
        self.max_spread_pct_to_trade = float(ex.get("max_spread_pct_to_trade", 0.10))
        self.partial_fill_timeout_seconds = int(ex.get("partial_fill_timeout_seconds", 30))
        self.cancel_replace_on_partial = bool(ex.get("cancel_replace_on_partial", True))
        self.max_slippage_bps = float(ex.get("max_slippage_bps", 10))
        self.block_strategy_if_slippage_bps_avg_exceeds = float(
            ex.get("block_strategy_if_slippage_bps_avg_exceeds", 25)
        )

    def can_trade_spread(self, spread_pct: float) -> tuple[bool, str]:
        if spread_pct > self.max_spread_pct_to_trade:
            return False, f"spread {spread_pct:.4f}% > max {self.max_spread_pct_to_trade}%"
        return True, "ok"

    def build_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        mid_price: float,
        spread_pct: float,
        tick_size: float = 0.01,
    ) -> OrderRequest | None:
        allowed, _ = self.can_trade_spread(spread_pct)
        if not allowed:
            return None

        if self.prefer_limit_orders:
            offset = self.limit_order_offset_ticks * tick_size
            if side == "buy":
                limit_price = round(mid_price - offset, 2)
            else:
                limit_price = round(mid_price + offset, 2)
            return OrderRequest(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=OrderType.LIMIT,
                limit_price=limit_price,
                expected_price=mid_price,
            )
        return OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            expected_price=mid_price,
        )

    def record_fill(
        self,
        state: ExecutionState,
        symbol: str,
        side: str,
        quantity: int,
        fill_price: float,
        expected_price: float,
    ) -> None:
        if expected_price <= 0:
            slippage_bps = 0.0
        else:
            if side == "buy":
                slippage_bps = (fill_price - expected_price) / expected_price * 10_000
            else:
                slippage_bps = (expected_price - fill_price) / expected_price * 10_000

        state.fill_history.append(
            FillReport(
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=fill_price,
                expected_price=expected_price,
                slippage_bps=slippage_bps,
                timestamp=datetime.utcnow(),
            )
        )

        n = len(state.fill_history)
        if n > 0:
            state.strategy_slippage_bps_avg = sum(f.slippage_bps for f in state.fill_history) / n
            if state.strategy_slippage_bps_avg > self.block_strategy_if_slippage_bps_avg_exceeds:
                state.strategy_blocked = True

    def should_block_strategy(self, state: ExecutionState) -> bool:
        return state.strategy_blocked

    def partial_fill_should_cancel_replace(self, filled_qty: int, requested_qty: int) -> bool:
        if not self.cancel_replace_on_partial:
            return False
        return 0 < filled_qty < requested_qty
