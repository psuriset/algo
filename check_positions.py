#!/usr/bin/env python3
"""Print current Alpaca positions and equity."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker

config = load_config(Path(__file__).parent / "config" / "default.yaml")
broker = AlpacaBroker(config)
equity = broker.get_equity()
positions = broker.get_positions()

print(f"Equity: ${equity:,.2f}")
print(f"Open positions: {len(positions)}")
if positions:
    print()
    print("Symbol    Qty    Side   Market value    Unrealized P&L")
    print("-" * 55)
    for p in positions:
        print(f"{p['symbol']:<9} {p['qty']:>5}   {str(p['side']):<6}  ${p['market_value']:>12,.2f}   ${p['unrealized_pl']:>+10,.2f}")
else:
    print("(No open positions)")
