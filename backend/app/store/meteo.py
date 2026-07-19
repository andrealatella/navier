"""Open-Meteo environment store: the CAPE/shear grid."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MeteoPoint:
    """One grid node's hourly environment series."""

    lat: float
    lon: float
    cape: list[float]
    shear_ms: list[float]
    flow_ms: list[float] = field(default_factory=list)
    flow_dir: list[float] = field(default_factory=list)


def _parse_hour(t: str) -> datetime:
    """Open-Meteo hour strings are naive ISO in the requested tz (we use UTC)."""
    return datetime.fromisoformat(t).replace(tzinfo=UTC)


class MeteoStore:
    """Latest CAPE/shear grid + O(1) nearest-node sampling."""

    def __init__(self, step_deg: float = 0.5) -> None:
        self._step = step_deg
        self._times: list[str] = []
        self._points: list[MeteoPoint] = []
        self._index: dict[tuple[int, int], MeteoPoint] = {}
        self._updated_at: datetime | None = None

    def set(self, times: list[str], points: list[MeteoPoint]) -> None:
        self._times = times
        self._points = points
        self._index = {self._key(p.lon, p.lat): p for p in points}
        self._updated_at = datetime.now(UTC)

    def _key(self, lon: float, lat: float) -> tuple[int, int]:
        return (round(lat / self._step), round(lon / self._step))

    @property
    def step_deg(self) -> float:
        return self._step

    @property
    def available(self) -> bool:
        return bool(self._points and self._times)

    @property
    def times(self) -> list[str]:
        return self._times

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    def age_s(self, now: datetime | None = None) -> float | None:
        if self._updated_at is None:
            return None
        now = now or datetime.now(UTC)
        return (now - self._updated_at).total_seconds()

    def hour_index(self, now: datetime | None = None) -> int:
        """Index of the forecast hour nearest to `now` (default: real now)."""
        if not self._times:
            return 0
        now = now or datetime.now(UTC)
        best_i, best_d = 0, None
        for i, t in enumerate(self._times):
            d = abs((_parse_hour(t) - now).total_seconds())
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        return best_i

    def sample(
        self, lon: float, lat: float, hour_index: int | None = None
    ) -> tuple[float | None, float | None]:
        """(cape, shear_ms) at the grid node nearest to (lon, lat); (None, None) if empty."""
        if not self.available:
            return (None, None)
        i = self.hour_index() if hour_index is None else hour_index
        p = self._index.get(self._key(lon, lat))
        if p is None:
            p = min(self._points, key=lambda q: (q.lat - lat) ** 2 + (q.lon - lon) ** 2)
        cape = p.cape[i] if 0 <= i < len(p.cape) else None
        shear = p.shear_ms[i] if 0 <= i < len(p.shear_ms) else None
        return (cape, shear)

    def sample_flow(
        self, lon: float, lat: float, hour_index: int | None = None
    ) -> tuple[float | None, float | None]:
        """(speed_ms, bearing_deg) of the 700-500 hPa mean flow nearest (lon, lat)."""
        if not self.available:
            return (None, None)
        i = self.hour_index() if hour_index is None else hour_index
        p = self._index.get(self._key(lon, lat))
        if p is None:
            p = min(self._points, key=lambda q: (q.lat - lat) ** 2 + (q.lon - lon) ** 2)
        speed = p.flow_ms[i] if 0 <= i < len(p.flow_ms) else None
        bearing = p.flow_dir[i] if 0 <= i < len(p.flow_dir) else None
        return (speed, bearing)

    def heatmap(self, hour_index: int | None = None) -> dict:
        """The whole grid for one hour as a GeoJSON point FeatureCollection."""
        i = self.hour_index() if hour_index is None else hour_index
        if self._times:
            i = max(0, min(i, len(self._times) - 1))
        feats = []
        max_cape = 0.0
        for p in self._points:
            cape = p.cape[i] if 0 <= i < len(p.cape) else 0.0
            shear = p.shear_ms[i] if 0 <= i < len(p.shear_ms) else 0.0
            max_cape = max(max_cape, cape)
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
                    "properties": {"cape": round(cape), "shear": round(shear, 1)},
                }
            )
        return {
            "hour_index": i,
            "hour": self._times[i] if self._times else None,
            "hours": self._times,
            "grid_step_deg": self._step,
            "updated_ms": int(self._updated_at.timestamp() * 1000) if self._updated_at else None,
            "max_cape": round(max_cape),
            "grid": {"type": "FeatureCollection", "features": feats},
        }


meteo_store = MeteoStore()
