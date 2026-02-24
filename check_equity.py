#!/usr/bin/env python3
"""Print current Alpaca account equity."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_loader import load_config
from src.brokers.alpaca_client import AlpacaBroker

config = load_config(Path(__file__).parent / "config" / "default.yaml")
broker = AlpacaBroker(config)
equity = broker.get_equity()
print(f"Equity: ${equity:,.2f}")
