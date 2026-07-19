"""Intercept point, cone-crossing check and the Google Maps deep link."""

from __future__ import annotations

import math

from ..models import CellSnapshot
from ..processing.geo import compass_it, destination

LonLat = tuple[float, float]

KM_PER_DEG_LAT = 110.574


def _km_per_deg_lon(lat: float) -> float:
    return 111.320 * math.cos(math.radians(lat))


def intercept_point(
    cell: CellSnapshot,
    user: LonLat | None,
    horizon_min: float,
    offset_km: float,
) -> tuple[LonLat, bool, str]:
    """Where to head to meet `cell` on its flank."""
    lon, lat = cell.centroid
    if cell.motion is None or cell.motion.speed_kmh < 1.0:
        return (
            (lon, lat),
            False,
            "cella ferma: rotta verso la posizione attuale (tieni la distanza)",
        )

    bearing = cell.motion.bearing_deg
    fwd_lon, fwd_lat = destination(lon, lat, bearing, cell.motion.speed_kmh * horizon_min / 60.0)

    perp = bearing + 90.0
    if user is not None:
        east = (user[0] - lon) * _km_per_deg_lon(lat)
        north = (user[1] - lat) * KM_PER_DEG_LAT
        m_e, m_n = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
        cross = m_e * north - m_n * east
        perp = bearing - 90.0 if cross > 0 else bearing + 90.0

    target = destination(fwd_lon, fwd_lat, perp, offset_km)
    note = (
        f"intercetto sul fianco {compass_it(perp)} a {offset_km:.0f} km dal nucleo, "
        f"proiettato a +{horizon_min:.0f}′"
    )
    return target, True, note


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
