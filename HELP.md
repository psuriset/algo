# Algorithmic Trading App — Function Reference

This file explains each module and its main functions/classes so you can understand how the app works.

---

## Table of Contents

1. [Config loader](#1-config-loader-srcconfig_loaderpy)
2. [Universe & data rules](#2-universe--data-rules-srcuniversepy)
3. [Strategy (entry/exit)](#3-strategy-entryexit-srcstrategypy)
4. [Position sizing](#4-position-sizing-srcposition_sizingpy)
5. [Portfolio & drawdown risk](#5-portfolio--drawdown-risk-srcportfolio_riskpy)
6. [Execution](#6-execution-srcexecutionpy)
7. [Compliance (PDT)](#7-compliance-pdt-srccompliancepy)
8. [Trade filters](#8-trade-filters-srctrade_filterspy)
9. [Trading engine](#9-trading-engine-srctrading_enginepy)
10. [Alpaca broker](#10-alpaca-broker-srcbrokersalpaca_clientpy)
11. [Scripts you can run](#11-scripts-you-can-run)

---

## 1. Config loader (`src/config_loader.py`)

Loads the main YAML configuration used by the rest of the app.

### `load_config(path=None)`

- **What it does:** Reads `config/default.yaml` (or the path you pass) and returns a Python dictionary.
- **Arguments:** `path` — optional; if omitted, uses `config/default.yaml` next to the project root.
- **Returns:** `dict` with all config sections (universe, strategy, position_sizing, etc.).
- **Use when:** Any script or class needs to read app settings.

---

## 2. Universe & data rules (`src/universe.py`)

Handles **which symbols** you can trade, **when** (sessions), and **market quality** (spread, volume, volatility).

### `MarketCalendar(config)`

- **What it does:** Knows market sessions (pre-market, regular, after-hours) and holidays. All times are treated as US Eastern.
- **Methods:**
  - **`get_session_at(dt)`** — Returns whether `dt` is in pre_market, regular, after_hours, or closed (holiday).
  - **`is_trading_allowed(dt)`** — `True` only during the session where `trade_allowed` is true in config (usually regular hours).
  - **`add_holiday(d)`** — Adds a date to the holiday list so that day is treated as closed.

### `UniverseFilter(config)`

- **What it does:** Restricts trading to a list of symbols and optional liquidity rules.
- **Method:**
  - **`is_eligible(symbol, avg_dollar_volume_30d=None, volume_vs_atr=None)`** — Returns `True` only if the symbol is in the config list and (if provided) passes min dollar volume and volume/ATR checks.

### `MarketQualityGate(config)`

- **What it does:** Blocks a trade if spread is too wide, volume/ATR too low, or volatility spike is on.
- **Method:**
  - **`check(spread_pct=None, volume_atr_ratio=None, current_atr_multiple=None)`** — Returns a `MarketQualityResult` with `ok` True/False and a `reason` string (e.g. "spread 0.15% > max 0.10%").

---

## 3. Strategy (entry/exit) (`src/strategy.py`)

Mechanical **when to buy** and **when to sell** for the trend-following strategy.

### `_atr(high, low, close, period)`

- **What it does:** Computes Average True Range (ATR) over `period` bars. Used for volatility filters and position sizing.
- **Returns:** pandas Series of ATR values.

### `TrendFollowingStrategy(config)`

- **What it does:** Implements the default strategy: price above slow MA, pullback to fast MA, with a volatility (ATR) filter. Exits are defined before entries (stop, target, time, kill-switch). Supports **player_focus** (institutional/retail/neutral) and optional **candlestick filter**: only enter when a pattern (e.g. bullish_engulfing, hammer, doji) appears on the last bar — see `src/candlestick.py` and config `strategy.candlestick_filter`.
- **Methods:**
  - **`atr_pct(df)`** — Returns ATR as a percentage of close (e.g. for “ATR%”).
  - **`generate_entry(symbol, df, spread_pct=None, atr_multiple_now=None)`** — Decides if there is a **buy** signal: uptrend + pullback + volatility filter. Returns an `EntrySignal` (with stop_pct, take_profit_pct, time_bars_exit) or `None` if no signal.
  - **`check_exit(symbol, entry_price, current_price, bars_held, spread_pct=None, atr_multiple=None)`** — Decides if you should **sell**: returns an `ExitSignal` for stop-loss, take-profit, time exit, or kill-switch (spread/volatility blow-out), or `None` if no exit.

### Data classes

- **`EntrySignal`** — Holds symbol, side, stop_pct, take_profit_pct, time_bars_exit, and extra metadata.
- **`ExitSignal`** — Holds symbol, exit reason (e.g. STOP_LOSS, TAKE_PROFIT), and metadata.

---

## 4. Position sizing (`src/position_sizing.py`)

Computes **how many shares** to trade and enforces risk and exposure limits.

### `PositionSizer(config)`

- **What it does:** Sizes positions so risk per trade is a set % of account; caps exposure per symbol and per sector; can reduce size in high volatility.
- **Methods:**
  - **`size_position(account_equity, price, stop_distance_pct, symbol, current_positions, sector_exposure_pct, symbol_sector=None, atr_pct=None)`** — Returns a `PositionSizingResult` (shares, notional, risk_amount, risk_pct). If the symbol would exceed max exposure it caps size instead of rejecting. If `atr_pct` is above the high-vol threshold, shares are multiplied by the configured factor (e.g. 0.5).
  - **`total_open_risk_pct(account_equity, positions_with_stops)`** — Sums the “at risk” (notional × stop_pct) of all positions as a % of equity. `positions_with_stops` is a list of `(notional, stop_pct)`.
  - **`would_exceed_max_open_risk(account_equity, current_open_risk_pct, new_trade_risk_pct)`** — Returns `True` if adding the new trade would push total open risk above the config limit.

### `PositionSizingResult`

- Fields: `shares`, `notional`, `risk_amount`, `risk_pct`, and optional `reject_reason` when the sizer cannot allow the trade.

---

## 5. Portfolio & drawdown risk (`src/portfolio_risk.py`)

**Daily loss limit**, **max drawdown / safe mode**, and **trade frequency** limits.

### `PortfolioRiskState`

- Holds: equity curve, peak equity, daily P&L %, daily trade count, per-symbol trade count, last trade date, safe_mode flag, and whether trading is stopped for the day.

### `PortfolioRiskManager(config)`

- **Methods:**
  - **`update_equity(state, dt, equity)`** — Appends (dt, equity) to the curve and updates peak equity.
  - **`current_drawdown_pct(state, current_equity)`** — Returns current drawdown from peak as a percentage.
  - **`check_daily_reset(state, today)`** — Resets daily counters if the date changed (new day).
  - **`can_trade(state, current_equity, symbol, today=None)`** — Returns `(allowed: bool, reason: str)`. Blocks if: safe mode and not recovered, daily loss limit hit, max drawdown hit (enters safe mode), max trades per day reached, or max trades per symbol per day reached.
  - **`record_trade(state, symbol, pnl_pct)`** — Increments daily and per-symbol counters and adds pnl_pct to daily P&L.

---

## 6. Execution (`src/execution.py`)

**Order type** (limit vs market), **spread check**, and **slippage** tracking.

### `ExecutionManager(config)`

- **Methods:**
  - **`can_trade_spread(spread_pct)`** — Returns `(allowed, reason)`. Blocks if spread is above the configured max.
  - **`build_order(symbol, side, quantity, mid_price, spread_pct, tick_size=0.01)`** — Builds an `OrderRequest`: limit order (with offset from mid) or market order depending on config. Returns `None` if spread is too wide.
  - **`record_fill(state, symbol, side, quantity, fill_price, expected_price)`** — Appends a fill to `state.fill_history`, updates average slippage in bps, and sets `strategy_blocked` if average slippage exceeds the config threshold.
  - **`should_block_strategy(state)`** — Returns whether the strategy is blocked due to slippage.
  - **`partial_fill_should_cancel_replace(filled_qty, requested_qty)`** — Returns whether to cancel/replace when there is a partial fill (based on config).

### Data classes

- **`OrderRequest`** — symbol, side, quantity, order_type (limit/market), limit_price, expected_price.
- **`FillReport`** — symbol, side, quantity, fill_price, expected_price, slippage_bps, timestamp.
- **`ExecutionState`** — fill_history, strategy_slippage_bps_avg, strategy_blocked.

---

## 7. Compliance (PDT) (`src/compliance.py`)

**Pattern Day Trader** rules when using a margin account.

### `ComplianceManager(config)`

- **Methods:**
  - **`can_day_trade(state, trade_date)`** — Returns `(allowed, reason)`. If equity &lt; $25k (configurable), allows at most 3 day trades in a rolling 5-business-day window; otherwise allows.
  - **`record_day_trade(state, trade_date)`** — Records that a day trade occurred on that date (for the rolling count).
  - **`update_equity(state, equity)`** — Updates the equity stored in PDT state.

### `PDTState`

- Holds: equity, day_trade_dates (list of dates of day trades used for the rolling window).

---

## 8. Trade filters (`src/trade_filters.py`)

**Macro blackout**, **earnings blackout**, and **volatility/spread “do not trade”.**

### `MacroEventBlackout(config)`

- **What it does:** No trading on configured dates or time windows (e.g. FOMC day, CPI release window).
- **Method:** **`check(dt)`** — Returns `FilterResult(allowed, reason)`. Blocks if `dt` falls on a blackout date or inside a blackout time window (ET).

### `EarningsBlackout(config)`

- **What it does:** No trading a symbol N days before/after its earnings date (dates come from config).
- **Method:** **`check(symbol, dt)`** — Returns `FilterResult`. Blocks if today is within `days_before`/`days_after` of any earnings date for that symbol.

### `VolatilityDoNotTrade(config)`

- **What it does:** Stricter “do not trade” when ATR% or spread is above thresholds.
- **Method:** **`check(atr_pct=None, spread_pct=None)`** — Returns `FilterResult`. Blocks if ATR% or spread exceeds the configured max.

---

## 9. Trading engine (`src/trading_engine.py`)

**Runs all gates in order** and returns whether to trade and the order/sizing to use.

### `TradingEngine(config=None, config_path=None)`

- **What it does:** Builds the calendar, universe filter, market quality gate, strategy, position sizer, portfolio risk, execution, compliance, and trade filters from config. Holds shared state (portfolio risk, execution, PDT).
- **Methods:**
  - **`update_equity(equity, dt=None)`** — Updates equity in portfolio risk and PDT state; used at the start of each run or when you get new account data.
  - **`is_trading_allowed(dt)`** — Convenience: returns whether the market session allows trading at `dt`.
  - **`run_entry_gates(symbol, dt, account_equity, current_positions, sector_exposure_pct, spread_pct, volume_atr_ratio=None, atr_multiple=None, ohlcv_df=None, symbol_sector=None)`** — Runs the full sequence: calendar → macro blackout → universe → earnings blackout → market quality → execution spread → volatility DNT → slippage block → portfolio risk → PDT → strategy entry → position sizing (with high-vol reduction) → max open risk check → build order. Returns a **`TradeDecision`**: `allowed` (bool), `reason` (str), and if allowed: `order_request`, `entry_signal`, `position_sizing`.
  - **`check_exit(symbol, entry_price, current_price, bars_held, spread_pct=None, atr_multiple=None)`** — Delegates to the strategy’s `check_exit`; returns an `ExitSignal` or `None`.

### `TradeDecision`

- Fields: `allowed`, `reason`, `order_request` (for the broker), `entry_signal`, `position_sizing`.

### `TradingEngineState`

- Holds: portfolio_risk state, execution state, PDT state.

---

## 10. Alpaca broker (`src/brokers/alpaca_client.py`)

Talks to **Alpaca** for account, data, and orders.

### `AlpacaBroker(config)`

- **What it does:** Uses Alpaca API (paper or live from config). Needs `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in the environment (or in config). Uses IEX data feed by default so free accounts work.
- **Methods:**
  - **`get_equity()`** — Current account equity.
  - **`get_positions()`** — List of open positions (symbol, qty, side, market_value, cost_basis, unrealized_pl).
  - **`get_bars(symbol, timeframe="1Day", start=None, end=None, limit=300)`** — OHLCV bars as a pandas DataFrame (open, high, low, close, volume).
  - **`get_latest_quote(symbol)`** — Returns `QuoteInfo` (bid, ask, mid, spread_pct) or `None`.
  - **`submit_order(order)`** — Sends an `OrderRequest` to Alpaca (limit or market); returns the Alpaca order object.
  - **`get_order(order_id)`** — Fetches one order by ID.
  - **`get_orders_for_date(trade_date)`** — Returns closed/filled orders submitted on that date (ET); used for daily summary.

---

## 11. Scripts you can run

| Script | Purpose |
|--------|--------|
| **`python run_example.py`** | Runs the engine once with **synthetic** OHLCV (no broker). Good for testing that entry gates and sizing work. |
| **`python run_alpaca.py`** | Runs the engine once with **Alpaca**: gets equity, positions, bars, quote for the first universe symbol; runs entry gates; submits order if allowed. |
| **`python run_alpaca_loop.py`** | Runs in a loop until market close: every N minutes checks **exits** for tracked positions (sells on stop/target/time/kill-switch), then checks **entries** for all symbols and submits buys. Uses `data/positions_tracked.json` for entry price/time. Stops on close or daily limit. |
| **`python check_equity.py`** | Prints current Alpaca account equity. |
| **`python check_prices.py`** | Prints latest price (quote or last close) for each symbol in the universe. |
| **`python show_daily_summary.py [YYYY-MM-DD]`** | Prints that day’s summary: equity, trades (filled orders), open positions. No date = today. |

---

## Quick reference: order of checks in `run_entry_gates`

1. Market session (trading allowed?)
2. Macro blackout
3. Symbol in universe
4. Earnings blackout for symbol
5. Market quality (spread, volume/ATR, volatility spike)
6. Execution spread (can trade?)
7. Volatility DNT (ATR%, spread)
8. Slippage block (strategy blocked?)
9. Portfolio risk (daily loss, drawdown, trade count)
10. PDT (day-trade limit)
11. Strategy entry signal (trend + pullback + vol filter)
12. Position sizing (with high-vol reduction) and max open risk
13. Build order (limit/market)

If all pass → `TradeDecision(allowed=True, order_request=..., ...)`. Otherwise → `TradeDecision(allowed=False, reason="...")`.
