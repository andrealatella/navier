"""Intercept point, road snapping, feasibility, cone crossing and the Maps deep link."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable

from ..models import CellSnapshot
from ..processing.geo import compass_it, destination, haversine_km
from ..processing.sun import SolarPosition
from .visibility import RainFn, ViewProbe, sight_penalty_km

LonLat = tuple[float, float]
SnapFn = Callable[[LonLat], Awaitable[LonLat | None]]

KM_PER_DEG_LAT = 110.574

_SNAP_GOOD_KM = 0.5
_FAN = ((-50.0, 1.0), (-25.0, 1.0), (25.0, 1.0), (50.0, 1.0), (0.0, 1.3))
_CONE_PENALTY_KM = 3.0
_ANGLE_COST_KM_PER_DEG = 0.02


def _km_per_deg_lon(lat: float) -> float:
    return 111.320 * math.cos(math.radians(lat))


def _local_km(origin: LonLat, point: LonLat) -> tuple[float, float]:
    east = (point[0] - origin[0]) * _km_per_deg_lon(origin[1])
    north = (point[1] - origin[1]) * KM_PER_DEG_LAT
    return east, north


def inflow_flank(cell: CellSnapshot, user: LonLat | None) -> tuple[float, str]:
    """Compass bearing of the flank to sit on, and what decided it."""
    if cell.motion is None:
        return 0.0, "default"
    bearing = cell.motion.bearing_deg
    dev = cell.motion_deviation_deg
    if dev is not None and dev > 0:
        return (bearing + 90.0) % 360.0, "destrorsa"
    if dev is not None and dev < 0:
        return (bearing - 90.0) % 360.0, "sinistrorsa"
    if user is not None:
        east, north = _local_km(cell.centroid, user)
        m_e, m_n = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
        cross = m_e * north - m_n * east
        perp = bearing - 90.0 if cross > 0 else bearing + 90.0
        return perp % 360.0, "utente"
    return (bearing + 90.0) % 360.0, "default"


def _projected_core(cell: CellSnapshot, horizon_min: float) -> LonLat:
    lon, lat = cell.centroid
    if cell.motion is None:
        return (lon, lat)
    run_km = cell.motion.speed_kmh * horizon_min / 60.0
    return destination(lon, lat, cell.motion.bearing_deg, run_km)


def _note(perp: float, why: str, offset_km: float, horizon_min: float) -> str:
    head = f"intercetto sul fianco {compass_it(perp)}"
    if why == "destrorsa":
        head += ", lato inflow di una cella destrorsa"
    elif why == "sinistrorsa":
        head += ", lato inflow di una cella sinistrorsa"
    return f"{head} a {offset_km:.0f} km dal nucleo, proiettato a +{horizon_min:.0f}′"


def intercept_point(
    cell: CellSnapshot,
    user: LonLat | None,
    horizon_min: float,
    offset_km: float,
) -> tuple[LonLat, bool, str]:
    """Where to head to meet `cell` on its inflow flank."""
    lon, lat = cell.centroid
    if cell.motion is None or cell.motion.speed_kmh < 1.0:
        return (
            (lon, lat),
            False,
            "cella ferma: rotta verso la posizione attuale (tieni la distanza)",
        )

    perp, why = inflow_flank(cell, user)
    core = _projected_core(cell, horizon_min)
    target = destination(core[0], core[1], perp, offset_km)
    return target, True, _note(perp, why, offset_km, horizon_min)


async def road_intercept_point(
    cell: CellSnapshot,
    user: LonLat | None,
    horizon_min: float,
    offset_km: float,
    snap: SnapFn,
    *,
    min_core_km: float,
    max_snap_km: float,
    rain_at: RainFn | None = None,
    sun: SolarPosition | None = None,
    probe: ViewProbe | None = None,
) -> tuple[LonLat, bool, str]:
    """Intercept point pulled onto the road network, best reachable candidate wins."""
    base, is_intercept, note = intercept_point(cell, user, horizon_min, offset_km)
    if not is_intercept:
        return base, is_intercept, note

    probe = probe or ViewProbe()

    core = _projected_core(cell, horizon_min)
    perp, _why = inflow_flank(cell, user)

    primary = await snap(base)
    if primary is not None:
        moved = haversine_km(base[0], base[1], primary[0], primary[1])
        core_km = haversine_km(core[0], core[1], primary[0], primary[1])
        clear = sight_penalty_km(primary, cell, probe, rain_at, sun) <= 0.0
        if moved <= _SNAP_GOOD_KM and core_km >= min_core_km and clear:
            return primary, True, note + _snap_suffix(moved)

    raws = [
        destination(core[0], core[1], (perp + da) % 360.0, offset_km * scale) for da, scale in _FAN
    ]
    snapped = await asyncio.gather(*(snap(p) for p in raws), return_exceptions=True)

    best: tuple[float, LonLat, float] | None = None
    pool: list[tuple[float, LonLat, LonLat]] = []
    if primary is not None:
        pool.append((0.0, base, primary))
    for (da, _scale), raw, got in zip(_FAN, raws, snapped, strict=False):
        if isinstance(got, BaseException) or got is None:
            continue
        pool.append((abs(da), raw, got))

    for angle, raw, point in pool:
        moved = haversine_km(raw[0], raw[1], point[0], point[1])
        if moved > max_snap_km:
            continue
        if haversine_km(core[0], core[1], point[0], point[1]) < min_core_km:
            continue
        score = moved + angle * _ANGLE_COST_KM_PER_DEG
        if _in_any_cone(point, cell):
            score += _CONE_PENALTY_KM
        score += sight_penalty_km(point, cell, probe, rain_at, sun)
        if best is None or score < best[0]:
            best = (score, point, moved)

    if best is None:
        return base, True, note + " · nessuna strada utile vicina, punto geometrico"
    return best[1], True, note + _snap_suffix(best[2])


def _snap_suffix(moved_km: float) -> str:
    if moved_km <= 0.15:
        return " · su strada"
    return f" · spostato su strada di {moved_km:.1f} km"


def cell_eta_to_point_min(cell: CellSnapshot, point: LonLat) -> float | None:
    """Minutes until the cell core reaches `point`, negative once it is past."""
    if cell.motion is None or cell.motion.speed_kmh < 1.0:
        return None
    east, north = _local_km(cell.centroid, point)
    b = math.radians(cell.motion.bearing_deg)
    along = east * math.sin(b) + north * math.cos(b)
    return along / cell.motion.speed_kmh * 60.0


def feasibility(
    cell: CellSnapshot | None,
    dest: LonLat,
    drive_min: float,
    margin_min: float,
) -> dict | None:
    """Can we get there before the cell does? The verdict a chaser actually acts on."""
    if cell is None:
        return None
    eta = cell_eta_to_point_min(cell, dest)
    if eta is None:
        return None
    margin = eta - drive_min

    if eta < 0:
        verdict = "si_allontana"
        text = f"la cella si allontana dal punto, passata da {abs(eta):.0f} minuti"
    elif margin >= margin_min:
        verdict = "in_tempo"
        text = f"ci arrivi {margin:.0f} minuti prima della cella"
    elif margin >= 0:
        verdict = "limite"
        text = f"al limite, {margin:.0f} minuti di margine"
    else:
        verdict = "tardi"
        text = f"arrivi {abs(margin):.0f} minuti dopo il passaggio della cella"

    return {
        "drive_min": round(drive_min, 1),
        "cell_min": round(eta, 1),
        "margin_min": round(margin, 1),
        "verdict": verdict,
        "text": text,
    }


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon for a single lon/lat ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def _in_any_cone(point: LonLat, cell: CellSnapshot) -> bool:
    for cone in cell.forecast_cones:
        ring = cone.get("coordinates", [[]])[0]
        if len(ring) >= 3 and _point_in_ring(point[0], point[1], ring):
            return True
    return False


def route_crosses_cones(coordinates: list[list[float]], cells: list[CellSnapshot]) -> list[int]:
    """IDs of cells whose forecast cone the route polyline passes through."""
    if not coordinates or not cells:
        return []
    step = max(1, len(coordinates) // 200)
    sampled = coordinates[::step]
    hit: set[int] = set()
    for c in cells:
        for cone in c.forecast_cones:
            ring = cone.get("coordinates", [[]])[0]
            if len(ring) >= 3 and any(_point_in_ring(p[0], p[1], ring) for p in sampled):
                hit.add(c.id)
                break
    return sorted(hit)


def maps_deeplink(lat: float, lon: float) -> str:
    """Google Maps directions deep link - no API key, uses the phone's location."""
    return (
        f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}&travelmode=driving"
    )
