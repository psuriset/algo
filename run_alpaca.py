#!/usr/bin/env python3
"""
Run the trading engine with Alpaca as broker.

Uses config broker section (broker.firm: alpaca, broker.paper).
Environment: APCA_API_KEY_ID, APCA_API_SECRET_KEY.
"""
import os
import sys
from pathlib import Path
from datetime import datetime
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config_loader import load_config
from src.trading_engine import TradingEngine
from src.brokers.alpaca_client import AlpacaBroker
from src.strategy import _atr


def main() -> None:
    config_path = Path(__file__).parent / "config" / "default.yaml"
    config = load_config(config_path)
    broker_cfg = config.get("broker", {})
    if broker_cfg.get("firm") != "alpaca":
        print("Config broker.firm is not 'alpaca'. Set broker.firm: alpaca and broker.paper: true|false.")
        sys.exit(1)

    broker = AlpacaBroker(config)
    engine = TradingEngine(config=config)

    account_equity = broker.get_equity()
    engine.update_equity(account_equity)
    engine.state.pdt.equity = account_equity

    positions = broker.get_positions()
    current_positions = {p["symbol"]: {"notional": p["market_value"], "stop_pct": 1.5} for p in positions}
    sector_exposure_pct = {}  # Optional: map sector -> current exposure %

    symbol = config.get("universe", {}).get("symbols", ["SPY"])[0]
    df = broker.get_bars(symbol, timeframe="1Day", limit=220)
    if df.empty or len(df) < 200:
        print(f"Not enough bars for {symbol} (got {len(df)}). Skip.")
        sys.exit(0)

    quote = broker.get_latest_quote(symbol)
    spread_pct = quote.spread_pct if quote else 0.15
    atr = _atr(df["high"], df["low"], df["close"], 14)
    atr_pct = (atr.iloc[-1] / df["close"].iloc[-1]) * 100 if len(atr) else None
    volume_atr_ratio = 1.5  # Placeholder; compute from bars if needed

    et = pytz.timezone("America/New_York")
    dt = datetime.now(et)
    decision = engine.run_entry_gates(
        symbol=symbol,
        dt=dt,
        account_equity=account_equity,
        current_positions=current_positions,
        sector_exposure_pct=sector_exposure_pct,
        spread_pct=spread_pct,
        volume_atr_ratio=volume_atr_ratio,
        atr_multiple=atr_pct / 1.0 if atr_pct else None,
        ohlcv_df=df,
        symbol_sector=None,
    )

    print("Entry decision:", decision.allowed, "—", decision.reason)
    if not decision.allowed:
        sys.exit(0)

    if decision.order_request:
        notional = (decision.position_sizing.notional if decision.position_sizing else 0) or 0
        buying_power = broker.get_buying_power()
        if notional > buying_power:
            print("Skip — insufficient buying power (need $%.0f, have $%.0f)" % (notional, buying_power))
            sys.exit(0)
        order = broker.submit_order(decision.order_request)
        print("Order submitted:", getattr(order, "id", order))
        if getattr(order, "limit_price", None) is not None:
            print("  Limit price:", order.limit_price, "Qty:", order.qty)


if __name__ == "__main__":
    main()
