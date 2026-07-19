"""Time-window parsing for dashboard queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# window key -> (lookback, time-series bucket width)
_WINDOWS: dict[str, tuple[timedelta, timedelta]] = {
    "15m": (timedelta(minutes=15), timedelta(minutes=1)),
    "1h": (timedelta(hours=1), timedelta(minutes=2)),
    "6h": (timedelta(hours=6), timedelta(minutes=15)),
    "24h": (timedelta(hours=24), timedelta(hours=1)),
    "7d": (timedelta(days=7), timedelta(hours=6)),
    "30d": (timedelta(days=30), timedelta(days=1)),
}
DEFAULT_WINDOW = "24h"


@dataclass(frozen=True)
class TimeWindow:
    key: str
    since: datetime
    bucket_seconds: int
    lookback_seconds: int


def resolve_window(window: str | None) -> TimeWindow:
    key = window if window in _WINDOWS else DEFAULT_WINDOW
    lookback, bucket = _WINDOWS[key]
    now = datetime.now(timezone.utc)
    return TimeWindow(
        key=key,
        since=now - lookback,
        bucket_seconds=int(bucket.total_seconds()),
        lookback_seconds=int(lookback.total_seconds()),
    )


def available_windows() -> list[str]:
    return list(_WINDOWS.keys())
