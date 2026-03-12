#!/usr/bin/env python3
"""
Run the trading engine in a loop until market close (no user interaction).

Checks for entry signals every N minutes during regular session; stops when
market closes or daily loss limit / safe mode is hit.
CLI: --live or --paper to override config.
"""
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime
import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config
from src.trading_engine import TradingEngine
from src.brokers.alpaca_client import AlpacaBroker
from src.strategy import _atr
from src.universe import MarketCalendar, SessionType
from src.position_tracker import load as load_tracked, add as add_tracked, remove as remove_tracked, update as update_tracked, bars_held
from src.strategy import ExitReason


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trading loop until market close")
    parser.add_argument("--live", action="store_true", help="Use live account (real money)")
    parser.add_argument("--paper", action="store_true", help="Use paper account (default)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print why each symbol is skipped (no trade)")
    args = parser.parse_args()
    if args.live and args.paper:
        parser.error("Use only one of --live or --paper")
    verbose = getattr(args, "verbose", False)

    config_path = PROJECT_ROOT / "config" / "default.yaml"
    config = load_config(config_path)
    if args.live:
        config.setdefault("broker", {})["paper"] = False
    elif args.paper:
        config.setdefault("broker", {})["paper"] = True

    broker_cfg = config.get("broker", {})
    if broker_cfg.get("firm") != "alpaca":
        print("Config broker.firm is not 'alpaca'. Exiting.")
        sys.exit(1)

    broker = AlpacaBroker(config)
    mode = "PAPER" if broker.paper else "LIVE (real money)"
    print("Broker mode:", mode)
    engine = TradingEngine(config=config)
    calendar = MarketCalendar(config)
    et = pytz.timezone("America/New_York")
    interval_sec = int(broker_cfg.get("check_interval_minutes", 5)) * 60
    tracker_path = PROJECT_ROOT / "data" / "positions_tracked.json"

    print("Running until market close (regular session). Check every", interval_sec // 60, "min. Ctrl+C to stop.")
    print("-" * 50)

    while True:
        dt = datetime.now(et)
        if not calendar.is_trading_allowed(dt):
            session = calendar.get_session_at(dt)
            if session == SessionType.CLOSED:
                print(dt.strftime("%Y-%m-%d %H:%M ET"), "Market closed. Stopping.")
                break
            print(dt.strftime("%Y-%m-%d %H:%M ET"), "Outside regular hours. Sleeping until next check.")
            time.sleep(interval_sec)
            continue

        print(dt.strftime("%H:%M ET"), "— in session, fetching account...")
        sys.stdout.flush()
        account_equity = broker.get_equity()
        engine.update_equity(account_equity)
        engine.state.pdt.equity = account_equity

        # Stop if portfolio risk says no more trading today
        can_trade, reason = engine.portfolio_risk.can_trade(
            engine.state.portfolio_risk, account_equity, "SPY", dt.date()
        )
        if not can_trade:
            print(dt.strftime("%Y-%m-%d %H:%M ET"), reason, "- Stopping for today.")
            break

        positions = broker.get_positions()
        tracked = load_tracked(tracker_path)
        # Sync tracker with broker: add any position broker has that we don't track (e.g. after restart)
        for p in positions:
            sym = p["symbol"]
            if sym not in tracked:
                cost = float(p.get("cost_basis") or 0)
                qty = int(float(p.get("qty") or 0))
                entry = cost / qty if qty else 0
                add_tracked(tracker_path, sym, qty, entry, 1.5)
        tracked = load_tracked(tracker_path)
        current_positions = {p["symbol"]: {"notional": p["market_value"], "stop_pct": tracked.get(p["symbol"], {}).get("stop_pct", 1.5)} for p in positions}
        sector_exposure_pct = {}
        symbols = config.get("universe", {}).get("symbols", ["SPY"])

        # Heartbeat: so you see the loop is running even when no trades
        print(dt.strftime("%H:%M ET"), "— equity $%.0f, checking %d symbols..." % (account_equity, len(symbols)))
        sys.stdout.flush()

        # ----- Sell decisions: check exit rules for each tracked position -----
        for symbol in list(tracked.keys()):
            pos = tracked[symbol]
            qty = int(pos.get("qty", 0))
            if qty <= 0:
                remove_tracked(tracker_path, symbol)
                continue
            if not any(p["symbol"] == symbol for p in positions):
                remove_tracked(tracker_path, symbol)
                continue
            try:
                quote = broker.get_latest_quote(symbol)
                if not quote:
                    continue
                entry_price = float(pos.get("entry_price", 0))
                if entry_price <= 0:
                    continue
                entry_time_iso = pos.get("entry_time", "")
                bars = bars_held(entry_time_iso, dt)
                partial_taken = bool(pos.get("partial_taken", False))
                trail_high_val = pos.get("trail_high")
                trail_high_f = float(trail_high_val) if trail_high_val is not None else None
                if partial_taken:
                    new_high = max(trail_high_f or entry_price, quote.mid)
                    update_tracked(tracker_path, symbol, trail_high=new_high)
                    trail_high_f = new_high
                # ATR% = (ATR/close)*100 for kill-switch (same unit as config max_atr_pct)
                atr_pct_exit = None
                if symbol in symbols:
                    try:
                        df = broker.get_bars(symbol, timeframe="1Day", limit=20)
                        if not df.empty and len(df) >= 14:
                            atr = _atr(df["high"], df["low"], df["close"], 14)
                            atr_pct_exit = (atr.iloc[-1] / df["close"].iloc[-1]) * 100
                    except Exception:
                        pass
                exit_signal = engine.check_exit(
                    symbol,
                    entry_price,
                    quote.mid,
                    bars,
                    quote.spread_pct,
                    atr_pct_exit,
                    partial_taken=partial_taken,
                    trail_high=trail_high_f,
                    current_qty=qty,
                )
                if exit_signal:
                    if exit_signal.reason == ExitReason.PARTIAL_TAKE_PROFIT:
                        qty_to_sell = exit_signal.metadata.get("qty_to_sell", max(1, qty // 2))
                        sell_order = engine.execution.build_order(symbol, "sell", qty_to_sell, quote.mid, quote.spread_pct)
                        if sell_order:
                            broker.submit_order(sell_order)
                            print(dt.strftime("%H:%M ET"), symbol, "SELL", qty_to_sell, "shares (partial @ 2%) —", exit_signal.reason.value)
                        remaining = qty - qty_to_sell
                        if remaining <= 0:
                            remove_tracked(tracker_path, symbol)
                        else:
                            update_tracked(tracker_path, symbol, qty=remaining, partial_taken=True, trail_high=quote.mid)
                    else:
                        sell_order = engine.execution.build_order(symbol, "sell", qty, quote.mid, quote.spread_pct)
                        if sell_order:
                            broker.submit_order(sell_order)
                            print(dt.strftime("%H:%M ET"), symbol, "SELL", qty, "shares —", exit_signal.reason.value)
                        remove_tracked(tracker_path, symbol)
            except Exception as e:
                print(dt.strftime("%H:%M ET"), symbol, "exit check skip —", type(e).__name__, str(e)[:60])
                continue

        if verbose:
            print(dt.strftime("%H:%M ET"), "Entry check: equity $%.0f, positions %d" % (account_equity, len(positions)))
        for symbol in symbols:
            try:
                df = broker.get_bars(symbol, timeframe="1Day", limit=220)
                if df.empty or len(df) < 200:
                    if verbose:
                        print("  %s: skip — not enough bars (got %d, need 200)" % (symbol, len(df) if not df.empty else 0))
                    continue
                quote = broker.get_latest_quote(symbol)
                spread_pct = quote.spread_pct if quote else 0.15
                atr = _atr(df["high"], df["low"], df["close"], 14)
                atr_pct = (atr.iloc[-1] / df["close"].iloc[-1]) * 100 if len(atr) else None

                decision = engine.run_entry_gates(
                    symbol=symbol,
                    dt=dt,
                    account_equity=account_equity,
                    current_positions=current_positions,
                    sector_exposure_pct=sector_exposure_pct,
                    spread_pct=spread_pct,
                    volume_atr_ratio=1.5,
                    atr_pct=atr_pct,
                    ohlcv_df=df,
                    symbol_sector=None,
                )
                if decision.allowed and decision.order_request:
                    notional = (decision.position_sizing.notional if decision.position_sizing else 0) or 0
                    buying_power = broker.get_buying_power()
                    if notional > buying_power:
                        print(dt.strftime("%H:%M ET"), symbol, "skip — insufficient buying power (need $%.0f, have $%.0f)" % (notional, buying_power))
                        continue
                    order = broker.submit_order(decision.order_request)
                    qty_bought = decision.position_sizing.shares if decision.position_sizing else 0
                    entry_price = float(df["close"].iloc[-1]) if not df.empty else quote.mid
                    stop_pct = decision.entry_signal.stop_pct if decision.entry_signal else 1.5
                    add_tracked(tracker_path, symbol, qty_bought, entry_price, stop_pct)
                    print(dt.strftime("%H:%M ET"), symbol, "BUY", qty_bought, "shares", getattr(order, "id", ""))
                    current_positions[symbol] = {"notional": notional, "stop_pct": stop_pct}
                else:
                    if verbose:
                        print("  %s: %s" % (symbol, decision.reason or "no entry signal"))
            except Exception as e:
                print(dt.strftime("%H:%M ET"), symbol, "skip —", type(e).__name__, str(e)[:80])
                continue

        print(dt.strftime("%H:%M ET"), "— no new entries. Next check in", interval_sec // 60, "min")
        sys.stdout.flush()
        time.sleep(interval_sec)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
