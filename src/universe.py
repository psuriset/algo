"""
Universe & data rules: high-liquidity symbols, market sessions, market quality gates.

- Trade only high-liquidity symbols (e.g. S&P 500 / top-volume ETFs).
- Use official market sessions: pre-market, regular, after-hours; handle holidays/half-days.
- Gate every trade on market quality: spread %, min volume/ATR, optional news spike block.
"""
from dataclasses import dataclass
from datetime import date, time, datetime
from enum import Enum
from typing import Any

import pandas as pd


class SessionType(Enum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


@dataclass
class SessionWindow:
    start: time
    end: time
    trade_allowed: bool


@dataclass
class MarketQualityResult:
    ok: bool
    reason: str
    spread_pct: float | None = None
    volume_atr_ratio: float | None = None
    volatility_spike: bool = False


class MarketCalendar:
    """Market sessions and holiday handling (ET assumed for US equity)."""

    def __init__(self, config: dict[str, Any]):
        sessions = config.get("market_sessions", {})
        self.sessions = {
            SessionType.PRE_MARKET: self._parse_session(sessions.get("pre_market", {})),
            SessionType.REGULAR: self._parse_session(sessions.get("regular", {})),
            SessionType.AFTER_HOURS: self._parse_session(sessions.get("after_hours", {})),
        }
        self.holidays: set[date] = set()
        for d in config.get("holidays", []):
            if isinstance(d, str):
                self.holidays.add(date.fromisoformat(d))
            elif hasattr(d, "date"):
                self.holidays.add(d)

    @staticmethod
    def _parse_session(raw: dict) -> SessionWindow:
        def parse_time(s: str) -> time:
            parts = s.split(":")
            return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

        return SessionWindow(
            start=parse_time(raw.get("start", "09:30")),
            end=parse_time(raw.get("end", "16:00")),
            trade_allowed=raw.get("trade_allowed", True),
        )

    def get_session_at(self, dt: datetime) -> SessionType:
        t = dt.time() if hasattr(dt, "time") else dt
        d = dt.date() if hasattr(dt, "date") else date.today()
        if d in self.holidays:
            return SessionType.CLOSED
        if self._in_window(t, self.sessions[SessionType.PRE_MARKET]):
            return SessionType.PRE_MARKET
        if self._in_window(t, self.sessions[SessionType.REGULAR]):
            return SessionType.REGULAR
        if self._in_window(t, self.sessions[SessionType.AFTER_HOURS]):
            return SessionType.AFTER_HOURS
        return SessionType.CLOSED

    @staticmethod
    def _in_window(t: time, w: SessionWindow) -> bool:
        if w.start <= w.end:
            return w.start <= t < w.end
        return t >= w.start or t < w.end

    def is_trading_allowed(self, dt: datetime) -> bool:
        session = self.get_session_at(dt)
        if session == SessionType.CLOSED:
            return False
        return self.sessions[session].trade_allowed

    def add_holiday(self, d: date) -> None:
        self.holidays.add(d)


class UniverseFilter:
    """Filter symbols by liquidity (min dollar volume, etc.)."""

    def __init__(self, config: dict[str, Any]):
        u = config.get("universe", {})
        self.symbols = list(u.get("symbols", []))
        self.min_avg_dollar_volume_30d = float(u.get("min_avg_dollar_volume_30d", 50_000_000))
        self.min_atr_multiple_for_volume = float(u.get("min_atr_multiple_for_volume", 0.5))

    def is_eligible(
        self,
        symbol: str,
        avg_dollar_volume_30d: float | None = None,
        volume_vs_atr: float | None = None,
    ) -> bool:
        if symbol not in self.symbols:
            return False
        if avg_dollar_volume_30d is not None and avg_dollar_volume_30d < self.min_avg_dollar_volume_30d:
            return False
        if volume_vs_atr is not None and volume_vs_atr < self.min_atr_multiple_for_volume:
            return False
        return True


class MarketQualityGate:
    """Gate every trade on spread %, min volume/ATR, optional news/volatility spike."""

    def __init__(self, config: dict[str, Any]):
        mq = config.get("market_quality", {})
        self.max_spread_pct = float(mq.get("max_spread_pct", 0.10))
        self.min_volume_atr_ratio = float(mq.get("min_volume_atr_ratio", 1.0))
        self.block_on_news_spike = bool(mq.get("block_on_news_spike", True))
        self.news_volatility_spike_atr_multiple = float(mq.get("news_volatility_spike_atr_multiple", 2.0))

    def check(
        self,
        spread_pct: float | None = None,
        volume_atr_ratio: float | None = None,
        current_atr_multiple: float | None = None,
    ) -> MarketQualityResult:
        if spread_pct is not None and spread_pct > self.max_spread_pct:
            return MarketQualityResult(
                ok=False,
                reason=f"spread {spread_pct:.4f}% > max {self.max_spread_pct}%",
                spread_pct=spread_pct,
            )
        if volume_atr_ratio is not None and volume_atr_ratio < self.min_volume_atr_ratio:
            return MarketQualityResult(
                ok=False,
                reason=f"volume/ATR {volume_atr_ratio:.4f} < min {self.min_volume_atr_ratio}",
                volume_atr_ratio=volume_atr_ratio,
            )
        if (
            self.block_on_news_spike
            and current_atr_multiple is not None
            and current_atr_multiple >= self.news_volatility_spike_atr_multiple
        ):
            return MarketQualityResult(
                ok=False,
                reason=f"volatility spike: ATR multiple {current_atr_multiple:.2f}",
                volatility_spike=True,
            )
        return MarketQualityResult(ok=True, reason="ok")
