"""What you can actually see from a chase position: rain on the sightline, sun angle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from ..models import CellSnapshot
from ..processing.geo import bearing_deg, destination, haversine_km
from ..processing.sun import SolarPosition, light_regime, regime_text, solar_position

LonLat = tuple[float, float]
RainFn = Callable[[float, float], float | None]

MIN_VIEW_KM = 1.0
RAIN_COST_KM_PER_KM = 2.5
BACKLIT_COST_KM = 4.0

_RAIN_CLEAR_KM = 0.5
_RAIN_HEAVY_KM = 2.0
_LIGHT_PENALTY = {"controluce": 30.0, "laterale": 5.0, "crepuscolo": 10.0, "notte": 15.0}


@dataclass(frozen=True)
class ViewProbe:
    """How finely the sightline is marched, and what counts as rain."""

    step_km: float = 0.5
    standoff_km: float = 4.0
    threshold_mmh: float = 2.0


class RainOnSight(NamedTuple):
    """Rain met along a sightline. `samples` is 0 when no grid answered at all."""

    blocked_km: float
    peak_mmh: float
    samples: int


def rain_on_sight(
    observer: LonLat,
    cell: CellSnapshot,
    rain_at: RainFn,
    probe: ViewProbe,
) -> RainOnSight:
    """Km of sightline running through rain, and the peak rate met on the way."""
    lon, lat = cell.centroid
    dist = haversine_km(observer[0], observer[1], lon, lat)
    usable = dist - probe.standoff_km
    if usable < probe.step_km or probe.step_km <= 0:
        return RainOnSight(0.0, 0.0, 0)

    bearing = bearing_deg(observer[0], observer[1], lon, lat)
    blocked = 0.0
    peak = 0.0
    seen = 0
    steps = int(usable / probe.step_km)
    for k in range(1, steps + 1):
        p = destination(observer[0], observer[1], bearing, k * probe.step_km)
        v = rain_at(p[0], p[1])
        if v is None:
            continue
        seen += 1
        peak = max(peak, v)
        if v >= probe.threshold_mmh:
            blocked += probe.step_km
    return RainOnSight(round(blocked, 2), round(peak, 1), seen)


def sun_for(cell: CellSnapshot, now: datetime | None = None) -> SolarPosition:
    """Solar position over the cell, good enough for every candidate around it."""
    lon, lat = cell.centroid
    return solar_position(now or datetime.now(UTC), lon, lat)


def sight_penalty_km(
    observer: LonLat,
    cell: CellSnapshot,
    probe: ViewProbe,
    rain_at: RainFn | None,
    sun: SolarPosition | None,
) -> float:
    """Cost of a candidate in detour-km equivalent, so it composes with the rest."""
    penalty = 0.0
    if rain_at is not None:
        penalty += rain_on_sight(observer, cell, rain_at, probe).blocked_km * RAIN_COST_KM_PER_KM
    if sun is not None:
        view = bearing_deg(observer[0], observer[1], cell.centroid[0], cell.centroid[1])
        if light_regime(sun, view) == "controluce":
            penalty += BACKLIT_COST_KM
    return penalty


def _rain_text(rain: RainOnSight) -> str:
    if rain.samples == 0:
        return "pioggia sulla linea di vista non nota"
    if rain.blocked_km <= _RAIN_CLEAR_KM:
        return "vista libera"
    if rain.blocked_km <= _RAIN_HEAVY_KM:
        return f"{rain.blocked_km:.1f} km di pioggia sulla linea di vista"
    return (
        f"vista chiusa da {rain.blocked_km:.1f} km di pioggia, picco {rain.peak_mmh:.0f} mm/h"
    )


def _score(blocked_km: float, regime: str) -> int:
    score = 100.0 - min(60.0, blocked_km * 20.0) - _LIGHT_PENALTY.get(regime, 0.0)
    return int(max(0.0, round(score)))


def view_quality(
    observer: LonLat,
    cell: CellSnapshot,
    probe: ViewProbe,
    *,
    rain_at: RainFn | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Whether the storm is actually watchable from `observer`, and why."""
    lon, lat = cell.centroid
    if haversine_km(observer[0], observer[1], lon, lat) < MIN_VIEW_KM:
        return None

    rain = RainOnSight(0.0, 0.0, 0)
    if rain_at is not None:
        rain = rain_on_sight(observer, cell, rain_at, probe)
    blocked, peak = rain.blocked_km, rain.peak_mmh

    sun = sun_for(cell, now)
    view = bearing_deg(observer[0], observer[1], lon, lat)
    regime = light_regime(sun, view)
    score = _score(blocked, regime)
    quality = "buona" if score >= 75 else "media" if score >= 45 else "scarsa"

    return {
        "rain_blocked_km": blocked,
        "rain_max_mmh": peak,
        "rain_known": rain.samples > 0,
        "sun_azimuth_deg": sun.azimuth_deg,
        "sun_elevation_deg": sun.elevation_deg,
        "light": regime,
        "score": score,
        "quality": quality,
        "text": f"{_rain_text(rain)}, {regime_text(regime, sun)}",
    }
