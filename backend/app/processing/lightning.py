"""Lightning clustering and jump detection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sklearn.cluster import DBSCAN

from ..config import Settings
from ..models import LightningCluster, LightningStrike
from .geo import haversine_km


@dataclass
class _ClusterState:
    """Carried across ticks so a cluster keeps its identity and rate history."""

    id: int
    lon: float
    lat: float
    rate_hist: deque[float] = field(default_factory=lambda: deque(maxlen=16))


class LightningAnalyzer:
    """Stateful: call `analyze()` each tick with the recent strike window."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._states: list[_ClusterState] = []
        self._next_id = 1

    def analyze(self, strikes: list[LightningStrike], now: datetime) -> list[LightningCluster]:
        window = timedelta(seconds=self._s.lightning_cluster_window_s)
        recent = [s for s in strikes if now - s.ts <= window]
        if len(recent) < self._s.lightning_cluster_min_samples:
            self._states = []
            return []

        coords = np.array([[s.lon, s.lat] for s in recent])
        labels = DBSCAN(
            eps=self._s.lightning_cluster_eps_deg,
            min_samples=self._s.lightning_cluster_min_samples,
        ).fit_predict(coords)

        minute_ago = now - timedelta(seconds=60)
        out: list[LightningCluster] = []
        new_states: list[_ClusterState] = []
        for lbl in sorted(set(labels) - {-1}):
            members = [recent[i] for i in range(len(recent)) if labels[i] == lbl]
            lon = float(np.mean([m.lon for m in members]))
            lat = float(np.mean([m.lat for m in members]))
            rate = float(sum(1 for m in members if m.ts >= minute_ago))

            state = self._adopt(lon, lat)
            trailing = list(state.rate_hist)
            state.rate_hist.append(rate)
            state.lon, state.lat = lon, lat
            new_states.append(state)

            jump = self._is_jump(rate, trailing)
            out.append(
                LightningCluster(
                    id=state.id,
                    centroid=(round(lon, 5), round(lat, 5)),
                    count=len(members),
                    rate_min=round(rate, 1),
                    jump=jump,
                )
            )
        self._states = new_states
        return out

    def _adopt(self, lon: float, lat: float) -> _ClusterState:
        """Reuse the nearest previous cluster (<10 km) so history/id carry over."""
        best = None
        for st in self._states:
            d = haversine_km(lon, lat, st.lon, st.lat)
            if d < 10.0 and (best is None or d < best[0]):
                best = (d, st)
        if best is not None:
            return best[1]
        st = _ClusterState(id=self._next_id, lon=lon, lat=lat)
        self._next_id += 1
        return st

    def _is_jump(self, rate: float, trailing: list[float]) -> bool:
        if rate < self._s.jump_min_rate or len(trailing) < 3:
            return False
        mean = sum(trailing) / len(trailing)
        return mean > 0 and rate >= self._s.jump_factor * mean
