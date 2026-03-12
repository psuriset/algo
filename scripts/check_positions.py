#!/usr/bin/env python3
"""Print current Alpaca positions and equity. Use --live or --paper to choose account."""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Live account")
    parser.add_argument("--paper", action="store_true", help="Paper account (default)")
    args = parser.parse_args()
    if args.live and args.paper:
        parser.error("Use only one of --live or --paper")

    config = load_config(PROJECT_ROOT / "config" / "default.yaml")
    if args.live:
        config.setdefault("broker", {})["paper"] = False
    elif args.paper:
        config.setdefault("broker", {})["paper"] = True

    broker = AlpacaBroker(config)
    equity = broker.get_equity()
    positions = broker.get_positions()
    mode = "LIVE" if not broker.paper else "paper"
    print(f"[{mode}] Equity: ${equity:,.2f}")
    print(f"Open positions: {len(positions)}")
    if positions:
        print()
        print("Symbol    Qty    Side   Market value    Unrealized P&L")
        print("-" * 55)
        for p in positions:
            print(f"{p['symbol']:<9} {p['qty']:>5}   {str(p['side']):<6}  ${p['market_value']:>12,.2f}   ${p['unrealized_pl']:>+10,.2f}")
    else:
        print("(No open positions)")

if __name__ == "__main__":
    main()
