#!/usr/bin/env bash
# Run the Alpaca trading loop at market open. Only runs when YOU schedule it (e.g. via cron).
# Nothing runs by default. Add to crontab only when you want: 30 9 * * 1-5 /path/to/algo/start_trading_at_market_open.sh
# See SCHEDULE.md for full instructions.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
export PATH="/usr/bin:/bin:/usr/local/bin:$PATH"
# Load API keys from .env if present (cron often has no env)
[ -f "$SCRIPT_DIR/.env" ] && set -a && source "$SCRIPT_DIR/.env" && set +a
python3 run_alpaca_loop.py
