#!/usr/bin/env python3
"""Show latest stock prices for tracked symbols (uses last quote when market is closed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker

def main():
    config = load_config(Path(__file__).parent / "config" / "default.yaml")
    symbols = config.get("universe", {}).get("symbols", ["SPY"])
    broker = AlpacaBroker(config)

    print("Symbol    Price         Bid        Ask        (source)")
    print("-" * 55)
    for symbol in symbols:
        q = broker.get_latest_quote(symbol)
        if q:
            print(f"{symbol:<9} ${q.mid:>8.2f}   ${q.bid:>8.2f}   ${q.ask:>8.2f}   quote")
        else:
            # When market is closed, quote can be empty; use last daily bar close
            df = broker.get_bars(symbol, timeframe="1Day", limit=1)
            if not df.empty:
                close = df["close"].iloc[-1]
                print(f"{symbol:<9} ${close:>8.2f}   --         --         last close")
            else:
                print(f"{symbol:<9} (no data)")

if __name__ == "__main__":
    main()
