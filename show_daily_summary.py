#!/usr/bin/env python3
"""
Show a summary for a given day whenever you ask.

Usage:
  python show_daily_summary.py           # today
  python show_daily_summary.py 2025-02-19   # specific date
"""
import sys
from pathlib import Path
from datetime import date, datetime
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker


def main() -> None:
    if len(sys.argv) >= 2:
        try:
            trade_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print("Use date as YYYY-MM-DD, e.g. 2025-02-19")
            sys.exit(1)
    else:
        et = pytz.timezone("America/New_York")
        trade_date = datetime.now(et).date()

    config = load_config(Path(__file__).parent / "config" / "default.yaml")
    broker = AlpacaBroker(config)

    equity = broker.get_equity()
    positions = broker.get_positions()
    orders = broker.get_orders_for_date(trade_date)

    # ----- print summary -----
    print()
    print("=" * 55)
    print(f"  DAILY SUMMARY — {trade_date}")
    print("=" * 55)
    print()
    print(f"  Account equity (now)    ${equity:>12,.2f}")
    print()
    print("  Trades this day         ", len(orders))
    if orders:
        print("  " + "-" * 50)
        for o in orders:
            side = (o.get("side") or "").lower()
            sym = o.get("symbol", "?")
            qty = o.get("qty") or 0
            price = o.get("filled_avg_price")
            price_s = f"${price:.2f}" if price is not None else "—"
            ts = o.get("filled_at") or o.get("submitted_at")
            ts_s = str(ts)[:19] if ts else ""
            print(f"    {side.upper():4}  {sym:6}  qty {qty:>5}  @ {price_s:>10}  {ts_s}")
        print("  " + "-" * 50)
    print()
    print("  Open positions          ", len(positions))
    if positions:
        print("  " + "-" * 50)
        for p in positions:
            sym = p.get("symbol", "?")
            qty = p.get("qty", 0)
            mv = p.get("market_value", 0)
            pl = p.get("unrealized_pl", 0)
            print(f"    {sym:6}  qty {qty:>5}  value ${mv:>10,.2f}  unrealized P&L ${pl:>+10,.2f}")
        print("  " + "-" * 50)
    print()
    print("=" * 55)
    print()


if __name__ == "__main__":
    main()
