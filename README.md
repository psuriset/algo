# Algorithmic Trading App

A rule-based algorithmic trading application that enforces **universe & data**, **entry/exit**, **position sizing**, **portfolio & drawdown**, **execution**, and **compliance** rules before any trade.

## Rules Implemented

### 1) Universe & Data
- **High-liquidity only**: Configurable symbols (e.g. S&P 500 / top-volume ETFs like SPY, QQQ).
- **Market sessions**: Pre-market (no trade), regular hours (trade), after-hours (no trade); holidays supported.
- **Market quality gate**: Max spread %, min volume/ATR ratio, optional block on volatility/news spike (ATR multiple).
- **Trade filters** (optional): **Macro-event blackout** (no trade on FOMC/CPI dates or time windows); **earnings blackout** per symbol (N days before/after earnings); **volatility/spread do-not-trade** (stricter ATR%/spread thresholds); **position sizing reduction** in high-vol regimes (e.g. half size when ATR% &gt; threshold).

### 2) Entry/Exit (Mechanical)
- **Default strategy**: Trend-following — price above 200D MA, pullback to 20D MA, volatility filter (max ATR%).
- **Exits defined before entries**:  
  - Stop-loss (hard)  
  - Take-profit (optional)  
  - Time-based (e.g. close after N bars)  
  - Kill-switch (spread or ATR multiple explodes)

### 3) Position Sizing
- **Risk per trade**: 0.25%–1% of account (configurable).
- **Max open risk**: Cap total at-risk (sum of stop distances) to 2%–5%.
- **Exposure limits**: Max % per symbol and per sector.

### 4) Portfolio & Drawdown
- **Daily loss limit**: e.g. -1% to -3% → stop trading for the day.
- **Max drawdown**: e.g. -10% → safe mode (paper only) until recovery to a better level.
- **Trade frequency**: Max trades per day and per symbol per day.

### 5) Execution
- **Limit orders preferred** in liquid names; spread gate (don’t trade if spread too wide).
- **Partial fills**: Optional cancel/replace logic and timeout.
- **Slippage**: Track expected vs actual fill; block strategy if average slippage exceeds threshold.

### 6) Compliance
- **PDT**: Pattern Day Trader rules — $25,000 minimum equity and day-trade limit when below (current framework; may change per FINRA).
- **Best execution**: Note in config; app enforces limits only; broker retains best execution duty.

## Default: nothing runs automatically

The app **does not run or schedule by default**. No loop runs at market open unless you start it yourself or set up a schedule (see `SCHEDULE.md`). Run scripts only when you want to trade.

## Project Layout

```
algo/
├── config/
│   └── default.yaml      # All parameters (universe, strategy, risk, execution, broker, compliance)
├── src/
│   ├── config_loader.py  # Load YAML config
│   ├── universe.py       # Market calendar, universe filter, market quality gate
│   ├── strategy.py       # Trend-following entry/exit (extensible to mean reversion/breakout)
│   ├── position_sizing.py
│   ├── portfolio_risk.py
│   ├── execution.py
│   ├── compliance.py
│   ├── trading_engine.py # Orchestrates all gates and produces trade decision
│   └── brokers/
│       └── alpaca_client.py  # Alpaca: account, bars, quotes, order submission
├── run_example.py        # Example: run entry gates with sample OHLCV (no broker)
├── run_alpaca.py         # Run engine with Alpaca as broker (paper/live)
├── show_daily_summary.py # Show that day's summary (trades, positions, equity)
├── requirements.txt
└── README.md
```

## Setup

```bash
cd algo
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

## Broker: Alpaca

The app is configured for **Alpaca** as the broker. In `config/default.yaml`:

- `broker.firm: alpaca`
- `broker.paper: true` (use `false` for live)

Set environment variables (never commit keys):

- `APCA_API_KEY_ID` – Alpaca API key
- `APCA_API_SECRET_KEY` – Alpaca secret key

Paper base URL is used automatically when `paper: true`. Then run:

```bash
python run_alpaca.py
```

This uses your Alpaca account (paper or live) for equity and positions, fetches daily bars and latest quote for the first universe symbol, runs all entry gates, and submits the order to Alpaca if allowed.

## Run Example (no broker)

```bash
python run_example.py
```

This runs the full entry gate sequence for a sample symbol (SPY) with synthetic OHLCV and prints whether the trade is allowed and the order/sizing details.

## Configuration

Edit `config/default.yaml` to:

- Set **universe** symbols and liquidity filters.
- Adjust **market_sessions** (pre-market, regular, after-hours) and **market_quality** (spread %, volume/ATR, news spike).
- Tune **strategy** (e.g. MA periods, stop/target, time exit, kill-switch).
- Set **position_sizing** (risk per trade, max open risk, symbol/sector caps).
- Set **portfolio_risk** (daily loss limit, max drawdown, safe mode, trade frequency).
- Set **execution** (limit vs market, spread gate, slippage limits).
- Set **compliance** (PDT minimum equity, margin account flag).

## Extending the App

- **Strategies**: Add `MeanReversionStrategy` or `BreakoutStrategy` in `strategy.py` and select via `strategy.type` in config.
- **Data**: Replace sample data with your data provider (e.g. Alpaca, Polygon) and feed OHLCV + spread/volume/ATR into `TradingEngine.run_entry_gates`.
- **Broker**: Use `order_request` from `TradeDecision` to send limit/market orders via your broker API; record fills in `ExecutionManager.record_fill` for slippage and strategy blocking.

## Disclaimer

This app is for educational and research use. Trading involves risk. PDT and other rules may change. Always ensure compliance with your broker and applicable regulations.
