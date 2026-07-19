"""DPC criticality bulletin store: the official alert zones."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

RANK = {"verde": 0, "giallo": 1, "arancione": 2, "rosso": 3}


def parse_level(text: str | None) -> str:
    """Map a DPC level string ('… / ALLERTA GIALLA') to verde/giallo/arancione/rosso."""
    t = (text or "").upper()
    if "ROSSA" in t:
        return "rosso"
    if "ARANCIONE" in t:
        return "arancione"
    if "GIALLA" in t:
        return "giallo"
    return "verde"


def _max_level(*levels: str) -> str:
    return max(levels, key=lambda x: RANK.get(x, 0))


@dataclass
class _Zone:
    hydro: str
    bbox: tuple[float, float, float, float]
    rings: list[list[tuple[float, float]]]


def _dp(points: list, tol: float) -> list:
    """Douglas-Peucker simplify a coordinate ring (planar lon/lat, tol in degrees)."""
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    imax, dmax = 0, 0.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if seg2 == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / seg2
            t = max(0.0, min(1.0, t))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d > dmax:
            imax, dmax = i, d
    if dmax <= tol:
        return [points[0], points[-1]]
    return _dp(points[: imax + 1], tol)[:-1] + _dp(points[imax:], tol)


def _simplify_geom(geom: dict, tol: float) -> dict:
    """Simplify every ring of a Polygon/MultiPolygon; keep rings with ≥4 points."""

    def ring(coords: list) -> list | None:
        s = _dp([(float(x), float(y)) for x, y in coords], tol)
        if len(s) >= 4 and s[0] != s[-1]:
            s = s + [s[0]]
        return [list(p) for p in s] if len(s) >= 4 else None

    t = geom.get("type")
    if t == "Polygon":
        rings = [r for c in geom["coordinates"] if (r := ring(c))]
        return {"type": "Polygon", "coordinates": rings}
    if t == "MultiPolygon":
        polys = []
        for poly in geom["coordinates"]:
            rings = [r for c in poly if (r := ring(c))]
            if rings:
                polys.append(rings)
        return {"type": "MultiPolygon", "coordinates": polys}
    return geom


def _rings_of(geom: dict) -> list[list[tuple[float, float]]]:
    """Outer rings of a Polygon / MultiPolygon as lists of (lon, lat)."""
    t = geom.get("type")
    coords = geom.get("coordinates") or []
    rings: list[list[tuple[float, float]]] = []
    if t == "Polygon":
        if coords:
            rings.append([(float(x), float(y)) for x, y in coords[0]])
    elif t == "MultiPolygon":
        for poly in coords:
            if poly:
                rings.append([(float(x), float(y)) for x, y in poly[0]])
    return rings


def _bbox(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)


def _point_in_rings(rings: list[list[tuple[float, float]]], lon: float, lat: float) -> bool:
    """True if (lon, lat) is inside any ring (even-odd ray cast; holes ignored)."""
    for ring in rings:
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat):
                x_cross = (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
                if lon < x_cross:
                    inside = not inside
            j = i
        if inside:
            return True
    return False


class AllerteStore:
    def __init__(self) -> None:
        self._wire_fc: dict | None = None
        self._issued: str | None = None
        self._zones: list[_Zone] = []
        self._updated_at: datetime | None = None

    def set(self, features: list[dict], issued: str, simplify_tol: float = 0.01) -> None:
        """Parse raw DPC features into a slim wire FC + a point-lookup index."""
        wire_feats = []
        zones: list[_Zone] = []
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            idraulico = parse_level(props.get("Per rischio idraulico"))
            idrogeologico = parse_level(props.get("Per rischio idrogeologico"))
            temporali = parse_level(props.get("Per rischio temporali"))
            shown = parse_level(props.get("Rappresentata nella mappa"))
            hydro = _max_level(idraulico, idrogeologico)
            if shown != "verde":
                wire_feats.append(
                    {
                        "type": "Feature",
                        "geometry": _simplify_geom(geom, simplify_tol),
                        "properties": {
                            "zone": props.get("Nome zona"),
                            "level": shown,
                            "idraulico": idraulico,
                            "idrogeologico": idrogeologico,
                            "temporali": temporali,
                            "hydro": hydro,
                        },
                    }
                )
            if hydro != "verde":
                rings = _rings_of(geom)
                if rings:
                    zones.append(_Zone(hydro=hydro, bbox=_bbox(rings), rings=rings))
        self._wire_fc = {"type": "FeatureCollection", "features": wire_feats}
        self._zones = zones
        self._issued = issued
        self._updated_at = datetime.now(UTC)

    @property
    def available(self) -> bool:
        return self._wire_fc is not None

    @property
    def issued(self) -> str | None:
        return self._issued

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    def level_at(self, lon: float, lat: float) -> str | None:
        """Hydro alert level (verde/giallo/arancione/rosso) of the zone covering the point."""
        for z in self._zones:
            w, s, e, n = z.bbox
            if not (w <= lon <= e and s <= lat <= n):
                continue
            if _point_in_rings(z.rings, lon, lat):
                return z.hydro
        return None

    def wire(self) -> dict:
        return {
            "available": self.available,
            "issued": self._issued,
            "updated_ms": int(self._updated_at.timestamp() * 1000) if self._updated_at else None,
            "zones": self._wire_fc or {"type": "FeatureCollection", "features": []},
        }


allerte_store = AllerteStore()
