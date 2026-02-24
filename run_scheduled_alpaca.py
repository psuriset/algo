#!/usr/bin/env python3
"""
Wait until market open (9:30 AM ET), then run run_alpaca_loop.py. Repeats daily.

Nothing runs by default. Only runs when YOU start this script (e.g. when you ask to schedule).
Run once (e.g. in background or screen): it will sleep until next 9:30 AM ET Mon–Fri,
start the trading loop, and when the loop exits (market close), wait until next open.
"""
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30


def next_market_open(now: datetime) -> datetime:
    """Return next 9:30 AM ET that is a weekday."""
    now_et = now.astimezone(ET)
    # Today 9:30 ET if we're before it and it's a weekday
    today_open = now_et.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if now_et.weekday() < 5 and now_et < today_open:
        return today_open
    # Otherwise next weekday 9:30
    d = now_et.date()
    for _ in range(8):
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon=0 .. Fri=4
            next_open = ET.localize(datetime(d.year, d.month, d.day, MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0))
            return next_open
    return today_open


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    loop_script = project_dir / "run_alpaca_loop.py"

    print("Scheduled Alpaca runner: will start trading loop at 9:30 AM ET (Mon–Fri). Ctrl+C to stop.")
    print("-" * 60)

    while True:
        now = datetime.now(ET)
        next_open = next_market_open(now)
        now_et = now.astimezone(ET)
        wait_sec = (next_open - now_et).total_seconds()
        if wait_sec > 0:
            next_open_str = next_open.strftime("%Y-%m-%d %H:%M ET")
            print(f"{now_et.strftime('%Y-%m-%d %H:%M ET')} — Waiting until {next_open_str} ({wait_sec / 60:.0f} min)")
            time.sleep(min(wait_sec, 60))  # wake every 60s to check (handles DST / clock drift)
            continue

        # Time to run
        print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')} — Starting trading loop.")
        try:
            subprocess.run([sys.executable, str(loop_script)], cwd=str(project_dir))
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        print("Loop exited. Waiting for next market open.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
