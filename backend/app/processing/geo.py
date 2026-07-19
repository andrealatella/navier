"""Small geodesy helpers on WGS84 lon/lat."""

from __future__ import annotations

import math

EARTH_R_KM = 6371.0088
_CARDINALS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two lon/lat points, in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial compass bearing from point 1 to point 2, degrees clockwise from N."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lon: float, lat: float, bearing: float, dist_km: float) -> tuple[float, float]:
    """Point reached going `dist_km` from (lon, lat) on the given compass bearing."""
    ang = dist_km / EARTH_R_KM
    br = math.radians(bearing)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(p1),
        math.cos(ang) - math.sin(p1) * math.sin(p2),
    )
    return (math.degrees(l2), math.degrees(p2))


def compass_it(bearing: float) -> str:
    """Bearing to an 8-point Italian cardinal label (N, NE, E, SE, S, SO, O, NO)."""
    return _CARDINALS[round((bearing % 360.0) / 45.0) % 8]
