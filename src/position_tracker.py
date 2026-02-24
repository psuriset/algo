"""Track open positions (entry price, time) for exit logic. Persisted to JSON."""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


def _default_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "positions_tracked.json"


def load(base_path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = base_path or _default_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save(data: dict[str, dict[str, Any]], base_path: Path | None = None) -> None:
    path = base_path or _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def add(base_path: Path | None, symbol: str, qty: int, entry_price: float, stop_pct: float) -> None:
    data = load(base_path)
    data[symbol.upper()] = {
        "qty": qty,
        "entry_price": entry_price,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "stop_pct": stop_pct,
    }
    save(data, base_path)


def remove(base_path: Path | None, symbol: str) -> None:
    data = load(base_path)
    data.pop(symbol.upper(), None)
    save(data, base_path)


def bars_held(entry_time_iso: str, now: datetime | None = None) -> int:
    """Days held (for daily bars)."""
    try:
        s = entry_time_iso.replace("Z", "+00:00")
        t = datetime.fromisoformat(s)
    except Exception:
        t = datetime.now(timezone.utc)
    now = now or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0, (now - t).days)
