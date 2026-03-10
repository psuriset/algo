#!/usr/bin/env python3
"""
Show sell strategy and timeline for each open position.

For every position: entry price/date, stop-loss level, take-profit level,
time-based exit (bars held vs exit-after), and kill-switch conditions.
Optionally fetches current price to show distance to stop/target and unrealized P&L.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker
from src.strategy import TrendFollowingStrategy
from src.position_tracker import load, bars_held


def _format_date(entry_time_iso: str | None) -> str:
    if not entry_time_iso:
        return "—"
    try:
        s = entry_time_iso.replace("Z", "+00:00")
        t = datetime.fromisoformat(s)
        return t.strftime("%Y-%m-%d %H:%M") if t else "—"
    except Exception:
        return str(entry_time_iso)[:16] if entry_time_iso else "—"


def main() -> None:
    config = load_config(PROJECT_ROOT / "config" / "default.yaml")
    broker = AlpacaBroker(config)
    strategy = TrendFollowingStrategy(config)
    tracker_path = PROJECT_ROOT / "data" / "positions_tracked.json"
    tracked = load(tracker_path)

    positions = broker.get_positions()
    if not positions:
        print("No open positions.")
        return

    stop_pct_default = strategy.stop_loss_pct
    take_pct = strategy.take_profit_pct
    time_bars = strategy.time_bars_exit
    ks_spread = strategy.kill_switch_max_spread_pct
    ks_atr = strategy.kill_switch_max_atr_multiple

    print("Sell strategy and timeline (from config + position tracker)")
    print("=" * 70)
    print(f"Strategy defaults: stop {stop_pct_default}% | take-profit {take_pct}% | time exit after {time_bars} bars | kill-switch: spread > {ks_spread}% or ATR multiple > {ks_atr}")
    print()

    for p in positions:
        symbol = p["symbol"]
        qty = p["qty"]
        market_value = float(p["market_value"] or 0)
        cost_basis = float(p["cost_basis"] or 0)
        unrealized_pl = float(p.get("unrealized_pl") or 0)

        info = tracked.get(symbol.upper(), {})
        entry_price = float(info.get("entry_price") or (cost_basis / qty if qty else 0))
        entry_time_iso = info.get("entry_time")
        stop_pct = float(info.get("stop_pct") or stop_pct_default)

        bars = bars_held(entry_time_iso) if entry_time_iso else None
        stop_price = entry_price * (1 - stop_pct / 100.0)
        target_price = entry_price * (1 + (take_pct or 0) / 100.0) if take_pct else None

        current_price = (market_value / qty) if qty else entry_price
        ret_pct = (current_price - entry_price) / entry_price * 100 if entry_price else 0
        dist_stop_pct = (current_price - stop_price) / current_price * 100 if current_price and stop_price else 0
        dist_target_pct = (target_price - current_price) / current_price * 100 if (target_price and current_price) else None

        print(f"  {symbol}  qty={qty}  entry=${entry_price:.2f}  entry_date={_format_date(entry_time_iso)}")
        print(f"    Stop-loss:    ${stop_price:.2f}  ({stop_pct}% below entry)  —  current ~{dist_stop_pct:+.1f}% above stop")
        if target_price:
            print(f"    Take-profit:  ${target_price:.2f}  ({take_pct}% above entry)  —  current ~{dist_target_pct:+.1f}% below target" if dist_target_pct is not None else f"    Take-profit:  ${target_price:.2f}  ({take_pct}% above entry)")
        if bars is not None:
            time_line = f"    Time exit:    bar {bars} of {time_bars}  (exit after {time_bars} bars)" + (f"  →  {time_bars - bars} bars left" if bars < time_bars else "  →  would exit on next check")
        else:
            time_line = f"    Time exit:    after {time_bars} bars  (entry date unknown; not in tracker)"
        print(time_line)
        print(f"    Kill-switch:  sell if spread > {ks_spread}% or ATR multiple > {ks_atr}")
        print(f"    Unrealized P&L: ${unrealized_pl:+,.2f}  ({ret_pct:+.2f}%)")
        print()

    print("(To see live prices, ensure market data is available; P&L above uses broker position values.)")


if __name__ == "__main__":
    main()
