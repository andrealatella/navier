"""In-memory sliding-window stores."""

from __future__ import annotations

from collections import deque
from datetime import timedelta

from ..models import LightningStrike, utcnow


class LightningStore:
    def __init__(self, window_min: float = 15.0) -> None:
        self._window = timedelta(minutes=window_min)
        self._strikes: deque[LightningStrike] = deque()

    def _prune(self) -> None:
        cutoff = utcnow() - self._window
        s = self._strikes
        while s and s[0].ts < cutoff:
            s.popleft()

    def add(self, strikes: list[LightningStrike]) -> None:
        self._strikes.extend(strikes)
        self._prune()

    def recent(self) -> list[LightningStrike]:
        self._prune()
        return list(self._strikes)

    def count(self) -> int:
        self._prune()
        return len(self._strikes)


lightning_store = LightningStore()


def serialize_strikes(strikes: list[LightningStrike]) -> list[dict]:
    """Compact wire form for the WS: [{t: epoch_ms, lat, lon}] (small payloads)."""
    return [
        {"t": int(s.ts.timestamp() * 1000), "lat": round(s.lat, 5), "lon": round(s.lon, 5)}
        for s in strikes
    ]
