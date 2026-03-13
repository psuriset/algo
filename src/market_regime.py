"""
Market regime score: 0–5 from SPY/QQQ trend, VIX, HYG rising, TLT falling.

Score 4–5: bullish, 2–3: neutral, 0–1: defensive.
Used to adjust position size (e.g. full size in bullish, reduced in defensive).
"""
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class RegimeResult:
    score: int
    condition: str  # "bullish" | "neutral" | "defensive"
    size_multiplier: float
    details: dict[str, bool | str]  # which rules passed, for logging


class MarketRegimeScorer:
    """
    score += 1 if SPY > MA50
    score += 1 if QQQ > MA50
    score += 1 if VIX < threshold (e.g. 20)
    score += 1 if HYG rising (close > MA)
    score += 1 if TLT falling (close < MA)
    """

    def __init__(self, config: dict[str, Any]):
        mr = config.get("market_regime", {})
        self.enabled = bool(mr.get("enabled", True))
        symbols = mr.get("symbols", {})
        self.symbol_spy = (symbols.get("spy") or "SPY").strip().upper()
        self.symbol_qqq = (symbols.get("qqq") or "QQQ").strip().upper()
        self.symbol_vix = (symbols.get("vix") or "VIX").strip().upper()
        self.symbol_hyg = (symbols.get("hyg") or "HYG").strip().upper()
        self.symbol_tlt = (symbols.get("tlt") or "TLT").strip().upper()
        self.ma_period_trend = int(mr.get("ma_period_trend", 50))
        self.ma_period_rising_falling = int(mr.get("ma_period_rising_falling", 20))
        self.vix_threshold = float(mr.get("vix_threshold", 20.0))
        mult = mr.get("size_multipliers", {})
        self.mult_bullish = float(mult.get("bullish", 1.0))
        self.mult_neutral = float(mult.get("neutral", 0.8))
        self.mult_defensive = float(mult.get("defensive", 0.5))

    def required_symbols(self) -> list[str]:
        return [self.symbol_spy, self.symbol_qqq, self.symbol_vix, self.symbol_hyg, self.symbol_tlt]

    def compute(self, bars: dict[str, pd.DataFrame]) -> RegimeResult:
        """
        bars: map symbol -> DataFrame with columns open, high, low, close (and datetime index).
        Missing or empty DataFrames are treated as no contribution (no +1).
        """
        details: dict[str, bool | str] = {}
        score = 0

        def _close(sym: str):
            df = bars.get(sym)
            if df is None or df.empty or "close" not in df.columns:
                return None
            return float(df["close"].iloc[-1])

        def _ma(sym: str, period: int):
            df = bars.get(sym)
            if df is None or len(df) < period or "close" not in df.columns:
                return None
            return float(df["close"].rolling(period).mean().iloc[-1])

        # SPY > MA50
        spy_c, spy_ma = _close(self.symbol_spy), _ma(self.symbol_spy, self.ma_period_trend)
        if spy_c is not None and spy_ma is not None:
            ok = spy_c > spy_ma
            details[f"{self.symbol_spy}>MA{self.ma_period_trend}"] = ok
            if ok:
                score += 1
        else:
            details[f"{self.symbol_spy}>MA{self.ma_period_trend}"] = "no data"

        # QQQ > MA50
        qqq_c, qqq_ma = _close(self.symbol_qqq), _ma(self.symbol_qqq, self.ma_period_trend)
        if qqq_c is not None and qqq_ma is not None:
            ok = qqq_c > qqq_ma
            details[f"{self.symbol_qqq}>MA{self.ma_period_trend}"] = ok
            if ok:
                score += 1
        else:
            details[f"{self.symbol_qqq}>MA{self.ma_period_trend}"] = "no data"

        # VIX < threshold
        vix_c = _close(self.symbol_vix)
        if vix_c is not None:
            ok = vix_c < self.vix_threshold
            details[f"{self.symbol_vix}<{self.vix_threshold}"] = ok
            if ok:
                score += 1
        else:
            details[f"{self.symbol_vix}<{self.vix_threshold}"] = "no data"

        # HYG rising (close > MA)
        hyg_c, hyg_ma = _close(self.symbol_hyg), _ma(self.symbol_hyg, self.ma_period_rising_falling)
        if hyg_c is not None and hyg_ma is not None:
            ok = hyg_c > hyg_ma
            details[f"{self.symbol_hyg} rising"] = ok
            if ok:
                score += 1
        else:
            details[f"{self.symbol_hyg} rising"] = "no data"

        # TLT falling (close < MA)
        tlt_c, tlt_ma = _close(self.symbol_tlt), _ma(self.symbol_tlt, self.ma_period_rising_falling)
        if tlt_c is not None and tlt_ma is not None:
            ok = tlt_c < tlt_ma
            details[f"{self.symbol_tlt} falling"] = ok
            if ok:
                score += 1
        else:
            details[f"{self.symbol_tlt} falling"] = "no data"

        if score >= 4:
            condition = "bullish"
            size_multiplier = self.mult_bullish
        elif score >= 2:
            condition = "neutral"
            size_multiplier = self.mult_neutral
        else:
            condition = "defensive"
            size_multiplier = self.mult_defensive

        return RegimeResult(
            score=score,
            condition=condition,
            size_multiplier=size_multiplier,
            details=details,
        )
