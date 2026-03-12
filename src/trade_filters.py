"""
Trade filters: macro-event blackout, earnings blackout, volatility/spread do-not-trade.

- Macro blackout: no trading on configured dates or time windows (e.g. FOMC, CPI).
- Earnings blackout: no trading a symbol N days before/after its earnings date.
- Volatility/spread DNT: do not trade when ATR% or spread exceeds thresholds.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

try:
    import pytz
except ImportError:
    pytz = None


@dataclass
class FilterResult:
    allowed: bool
    reason: str


def _parse_time(s: str) -> time:
    parts = s.strip().split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


class MacroEventBlackout:
    """No trading during configured macro-event dates or time windows (ET)."""

    def __init__(self, config: dict[str, Any]):
        tf = config.get("trade_filters", {})
        mb = tf.get("macro_blackout", {})
        self.enabled = bool(mb.get("enabled", True))
        self.blackout_dates: set[date] = set()
        for d in mb.get("blackout_dates", []):
            if isinstance(d, str):
                self.blackout_dates.add(_parse_date(d))
            elif hasattr(d, "year"):
                self.blackout_dates.add(d)
        self.blackout_windows: list[tuple[date, time, time]] = []
        for w in mb.get("blackout_windows", []):
            d = _parse_date(str(w.get("date", "")))
            start = _parse_time(str(w.get("start", "00:00")))
            end = _parse_time(str(w.get("end", "23:59")))
            self.blackout_windows.append((d, start, end))

    def check(self, dt: datetime) -> FilterResult:
        if not self.enabled:
            return FilterResult(allowed=True, reason="ok")
        d = dt.date() if hasattr(dt, "date") else dt
        t = dt.time() if hasattr(dt, "time") else time(0, 0)
        if d in self.blackout_dates:
            return FilterResult(allowed=False, reason=f"macro blackout date {d}")
        for win_date, start, end in self.blackout_windows:
            if d != win_date:
                continue
            if start <= end:
                if start <= t < end:
                    return FilterResult(allowed=False, reason=f"macro blackout window {d} {start}-{end}")
            else:
                if t >= start or t < end:
                    return FilterResult(allowed=False, reason=f"macro blackout window {d} {start}-{end}")
        return FilterResult(allowed=True, reason="ok")


class EarningsBlackout:
    """No trading a symbol N days before/after its earnings date."""

    def __init__(self, config: dict[str, Any]):
        tf = config.get("trade_filters", {})
        eb = tf.get("earnings_blackout", {})
        self.enabled = bool(eb.get("enabled", True))
        self.days_before = int(eb.get("days_before", 1))
        self.days_after = int(eb.get("days_after", 1))
        self.earnings_dates: dict[str, list[date]] = {}
        for sym, dates in eb.get("earnings_dates", {}).items():
            self.earnings_dates[sym.upper()] = [_parse_date(str(x)) for x in dates] if dates else []

    def check(self, symbol: str, dt: datetime) -> FilterResult:
        if not self.enabled:
            return FilterResult(allowed=True, reason="ok")
        d = dt.date() if hasattr(dt, "date") else dt
        sym = symbol.upper()
        for ed in self.earnings_dates.get(sym, []):
            start = ed - timedelta(days=self.days_before)
            end = ed + timedelta(days=self.days_after)
            if start <= d <= end:
                return FilterResult(allowed=False, reason=f"earnings blackout {symbol} around {ed}")
        return FilterResult(allowed=True, reason="ok")


class VolatilityDoNotTrade:
    """Do not trade when volatility (ATR%) or spread exceeds thresholds.
    Uses real ATR% (not ATR multiple). Spread threshold is tiered: core vs high_vol."""

    def __init__(self, config: dict[str, Any]):
        tf = config.get("trade_filters", {})
        vd = tf.get("volatility_do_not_trade", {})
        self.enabled = bool(vd.get("enabled", True))
        self.max_atr_pct = float(vd.get("max_atr_pct", 5.0))
        # Default 0.5% for core; 0.10/0.15% is too strict for IEX
        self.max_spread_pct = float(vd.get("max_spread_pct", 0.5))
        high_vol = vd.get("high_vol_symbols") or []
        self.high_vol_symbols = {s.upper().strip() for s in high_vol if s}
        self.high_vol_max_spread_pct = float(vd.get("high_vol_max_spread_pct", 1.0))

    def _max_spread_for_symbol(self, symbol: str | None) -> float:
        if symbol and self.high_vol_symbols and symbol.upper() in self.high_vol_symbols:
            return self.high_vol_max_spread_pct
        return self.max_spread_pct

    def check(
        self,
        atr_pct: float | None = None,
        spread_pct: float | None = None,
        symbol: str | None = None,
    ) -> FilterResult:
        if not self.enabled:
            return FilterResult(allowed=True, reason="ok")
        if atr_pct is not None and atr_pct > self.max_atr_pct:
            return FilterResult(allowed=False, reason=f"volatility DNT: ATR% {atr_pct:.2f} > {self.max_atr_pct}")
        max_spread = self._max_spread_for_symbol(symbol)
        if spread_pct is not None and spread_pct > max_spread:
            return FilterResult(allowed=False, reason=f"volatility DNT: spread {spread_pct:.2f}% > {max_spread}")
        return FilterResult(allowed=True, reason="ok")
