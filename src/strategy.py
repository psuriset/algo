"""
Entry/exit rules: mechanical strategy with defined exits before entries.

Default: Trend-following (price above 200D MA, pullback to 20D MA, volatility filter).
Exits: stop-loss (hard), take-profit (optional), time-based, kill-switch.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd
import numpy as np

from .candlestick import detect_any as candlestick_detect_any


class StrategyType(Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TIME_BARS = "time_bars"
    KILL_SWITCH = "kill_switch"
    SIGNAL_EXIT = "signal_exit"


@dataclass
class EntrySignal:
    symbol: str
    side: str  # "long" | "short"
    strength: float
    stop_pct: float
    take_profit_pct: float | None
    time_bars_exit: int
    metadata: dict[str, Any]


@dataclass
class ExitSignal:
    symbol: str
    reason: ExitReason
    metadata: dict[str, Any]


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


class PlayerFocus:
    """Strategy style: institutional (follow big volume), retail (faster/short horizon), neutral."""
    NEUTRAL = "neutral"
    INSTITUTIONAL = "institutional"
    RETAIL = "retail"


class TrendFollowingStrategy:
    """
    Price above slow MA + pullback to fast MA + volatility filter.
    Exits defined before entries: stop, optional target, time, kill-switch.
    Supports player_focus: institutional (volume filter), retail (faster MAs), neutral.
    """

    def __init__(self, config: dict[str, Any]):
        strat = config.get("strategy", {})
        tf = strat.get("trend_following", {})
        exits = strat.get("exits", {})

        self.player_focus = (strat.get("player_focus") or PlayerFocus.NEUTRAL).strip().lower()
        inst = strat.get("institutional", {})
        self.institutional_min_volume_ratio = float(inst.get("min_volume_ratio_vs_avg", 1.2))
        retail = strat.get("retail", {})
        retail_ma_fast = int(retail.get("ma_fast", 10))
        retail_ma_slow = int(retail.get("ma_slow", 50))
        retail_time_bars = int(retail.get("time_bars_exit", 10))

        self.ma_fast = int(tf.get("ma_fast", 20))
        self.ma_slow = int(tf.get("ma_slow", 200))
        if self.player_focus == PlayerFocus.RETAIL:
            self.ma_fast = retail_ma_fast
            self.ma_slow = retail_ma_slow
        self.pullback_touch_ma_fast = bool(tf.get("pullback_touch_ma_fast", True))
        self.atr_period = int(tf.get("volatility_filter_atr_period", 14))
        self.max_atr_pct_for_entry = float(tf.get("max_atr_pct_for_entry", 2.0))

        self.stop_loss_pct = float(exits.get("stop_loss_pct", 1.5))
        self.take_profit_pct = float(exits.get("take_profit_pct", 3.0)) or None
        self.time_bars_exit = int(exits.get("time_bars_exit", 20))
        if self.player_focus == PlayerFocus.RETAIL:
            self.time_bars_exit = retail_time_bars
        ks = exits.get("kill_switch", {})
        self.kill_switch_max_spread_pct = float(ks.get("max_spread_pct", 0.25))
        self.kill_switch_max_atr_multiple = float(ks.get("max_atr_multiple", 3.0))

        cf = strat.get("candlestick_filter", {})
        self.candlestick_enabled = bool(cf.get("enabled", False))
        self.candlestick_patterns = list(cf.get("patterns", []) or [])

    def atr_pct(self, df: pd.DataFrame) -> pd.Series:
        if df.empty or len(df) < self.atr_period:
            return pd.Series(dtype=float)
        atr = _atr(df["high"], df["low"], df["close"], self.atr_period)
        return (atr / df["close"]) * 100

    def generate_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        spread_pct: float | None = None,
        atr_multiple_now: float | None = None,
    ) -> EntrySignal | None:
        """Generate entry only when trend + pullback + volatility filter pass."""
        if df is None or len(df) < self.ma_slow:
            return None

        close = df["close"]
        atr_pct = self.atr_pct(df)
        if atr_pct.iloc[-1] > self.max_atr_pct_for_entry:
            return None

        ma_fast = close.rolling(self.ma_fast).mean()
        ma_slow = close.rolling(self.ma_slow).mean()

        price = close.iloc[-1]
        ma_f = ma_fast.iloc[-1]
        ma_s = ma_slow.iloc[-1]

        # Uptrend: price > 200D MA
        if price <= ma_s:
            return None
        # Pullback: price at or near 20D MA (e.g. within 0.5% or touch)
        if self.pullback_touch_ma_fast and abs(price - ma_f) / ma_f > 0.005:
            return None

        # Kill-switch: don't enter if spread/volatility already bad
        if spread_pct is not None and spread_pct > self.kill_switch_max_spread_pct:
            return None
        if atr_multiple_now is not None and atr_multiple_now > self.kill_switch_max_atr_multiple:
            return None

        # Institutional: only enter when volume is elevated (proxy for institutional activity)
        if self.player_focus == PlayerFocus.INSTITUTIONAL and "volume" in df.columns and len(df) >= 20:
            vol = df["volume"]
            avg_vol = vol.rolling(20).mean().iloc[-1]
            if avg_vol and avg_vol > 0:
                volume_ratio = vol.iloc[-1] / avg_vol
                if volume_ratio < self.institutional_min_volume_ratio:
                    return None

        # Candlestick filter: only enter when one of the configured patterns appears on the last bar(s)
        if self.candlestick_enabled and not candlestick_detect_any(df, self.candlestick_patterns):
            return None

        return EntrySignal(
            symbol=symbol,
            side="long",
            strength=1.0,
            stop_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            time_bars_exit=self.time_bars_exit,
            metadata={"ma_fast": ma_f, "ma_slow": ma_s, "atr_pct": atr_pct.iloc[-1]},
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
        """Check for stop, target, time, or kill-switch exit."""
        ret_pct = (current_price - entry_price) / entry_price * 100

        if ret_pct <= -self.stop_loss_pct:
            return ExitSignal(symbol=symbol, reason=ExitReason.STOP_LOSS, metadata={"ret_pct": ret_pct})
        if self.take_profit_pct and ret_pct >= self.take_profit_pct:
            return ExitSignal(symbol=symbol, reason=ExitReason.TAKE_PROFIT, metadata={"ret_pct": ret_pct})
        if bars_held >= self.time_bars_exit:
            return ExitSignal(symbol=symbol, reason=ExitReason.TIME_BARS, metadata={"bars_held": bars_held})
        if spread_pct is not None and spread_pct > self.kill_switch_max_spread_pct:
            return ExitSignal(symbol=symbol, reason=ExitReason.KILL_SWITCH, metadata={"spread_pct": spread_pct})
        if atr_multiple is not None and atr_multiple > self.kill_switch_max_atr_multiple:
            return ExitSignal(symbol=symbol, reason=ExitReason.KILL_SWITCH, metadata={"atr_multiple": atr_multiple})
        return None
