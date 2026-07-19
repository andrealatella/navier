"""Cell tracker: turns a reprojected dBZ grid into tracked storm cells."""

from __future__ import annotations

import itertools
import logging
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import rasterio.features
from pyproj import Transformer
from scipy import ndimage
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform as shp_transform

from ..config import Settings
from ..models import CellSnapshot, LightningCluster, Motion
from .geo import compass_it, haversine_km

logger = logging.getLogger("navier.processing.cells")

KM_PER_DEG_LAT = 111.194
_TO_LONLAT = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _norm(x: float, lo: float, hi: float) -> float:
    """Linear map [lo, hi] -> [0, 1], clamped."""
    if hi <= lo:
        return 0.0
    return _clamp01((x - lo) / (hi - lo))


def signed_deviation_deg(bearing: float, reference: float) -> float:
    """How far `bearing` sits off `reference`, in [-180, 180)."""
    return (bearing - reference + 180.0) % 360.0 - 180.0


@dataclass
class _Blob:
    """One segmented echo before it is matched to a track."""

    centroid: tuple[float, float]
    area_km2: float
    max_dbz: float
    polygon: dict


@dataclass
class _Track:
    """Persistent per-cell state carried across frames."""

    id: int
    born_ts: datetime
    last_ts: datetime
    lon: float
    lat: float
    misses: int = 0
    vel_e: float | None = None
    vel_n: float | None = None
    dbz_hist: deque[tuple[datetime, float]] = field(default_factory=lambda: deque(maxlen=6))
    sev_hist: deque[tuple[datetime, int]] = field(default_factory=lambda: deque(maxlen=32))
    spark_hist: deque[int] = field(default_factory=lambda: deque(maxlen=16))


class CellTracker:
    """Stateful tracker: feed it consecutive frames, get CellSnapshots out."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._tracks: dict[int, _Track] = {}
        self._ids = itertools.count(1)

    def update(
        self,
        ts: datetime,
        grid: np.ndarray,
        transform,
        *,
        clusters: list[LightningCluster] | None = None,
        cape: float | None = None,
        cape_at: Callable[[float, float], float | None] | None = None,
        flow_at: Callable[[float, float], tuple[float | None, float | None]] | None = None,
        user: tuple[float, float] | None = None,
    ) -> list[CellSnapshot]:
        """Ingest one frame (dBZ grid + its pixel->3857 affine) and return cells."""
        blobs = self._segment(grid, transform)
        matches = self._match(ts, blobs)

        snapshots: list[CellSnapshot] = []
        alive: set[int] = set()
        for tid, blob in matches:
            track = self._tracks[tid]
            self._advance_motion(track, ts, blob)
            track.dbz_hist.append((ts, blob.max_dbz))
            alive.add(tid)
            snapshots.append(
                self._snapshot(track, ts, blob, clusters or [], cape, cape_at, flow_at, user)
            )

        for tid, track in list(self._tracks.items()):
            if tid in alive:
                track.misses = 0
                continue
            track.misses += 1
            if track.misses > self._s.track_max_misses:
                del self._tracks[tid]

        snapshots.sort(key=lambda c: c.severity, reverse=True)
        return snapshots

    def reset(self) -> None:
        self._tracks.clear()

    def _segment(self, grid: np.ndarray, transform) -> list[_Blob]:
        """Label ≥ENVELOPE echo, keep strong/large blobs, vectorise their polygons."""
        mask = grid >= self._s.dbz_envelope
        if not mask.any():
            return []
        labels, n = ndimage.label(mask)
        if n == 0:
            return []

        ids = np.arange(1, n + 1)
        maxes = np.asarray(ndimage.maximum(grid, labels, ids), dtype=float)
        sizes = np.bincount(labels.ravel())[1:]
        coms = ndimage.center_of_mass(grid, labels, ids)

        px = abs(transform.a)
        py = abs(transform.e)

        keep: dict[int, _Blob] = {}
        for k, lbl in enumerate(ids):
            if maxes[k] < self._s.dbz_core:
                continue
            row, col = coms[k]
            x, y = transform * (col + 0.5, row + 0.5)
            lon, lat = _TO_LONLAT.transform(x, y)
            cos2 = math.cos(math.radians(lat)) ** 2
            area_km2 = float(sizes[k]) * px * py * cos2 / 1e6
            if area_km2 < self._s.min_area_km2:
                continue
            keep[int(lbl)] = _Blob(
                centroid=(lon, lat),
                area_km2=area_km2,
                max_dbz=float(maxes[k]),
                polygon={},
            )
        if not keep:
            return []

        polys: dict[int, list[Polygon]] = {}
        li32 = labels.astype(np.int32)
        for geom, val in rasterio.features.shapes(li32, mask=(labels > 0), transform=transform):
            v = int(val)
            if v in keep:
                polys.setdefault(v, []).append(shape(geom))

        out: list[_Blob] = []
        for lbl, blob in keep.items():
            parts = polys.get(lbl)
            if not parts:
                continue
            poly = max(parts, key=lambda p: p.area)
            poly = poly.simplify(self._s.poly_simplify_deg * 111_000)
            lonlat = shp_transform(lambda xs, ys: _TO_LONLAT.transform(xs, ys), poly)
            blob.polygon = lonlat.__geo_interface__
            out.append(blob)
        return out

    def _match(self, ts: datetime, blobs: list[_Blob]) -> list[tuple[int, _Blob]]:
        tracks = list(self._tracks.values())
        if not tracks:
            return [(self._birth(ts, b), b) for b in blobs]
        if not blobs:
            return []

        FORBID = 1e6
        cost = np.full((len(tracks), len(blobs)), FORBID)
        for i, tr in enumerate(tracks):
            dt_h = max((ts - tr.last_ts).total_seconds() / 3600.0, 1e-6)
            gate_km = self._s.track_gate_kmh * dt_h
            for j, b in enumerate(blobs):
                d = haversine_km(tr.lon, tr.lat, b.centroid[0], b.centroid[1])
                if d <= gate_km:
                    cost[i, j] = d
        rows, cols = linear_sum_assignment(cost)

        matched: list[tuple[int, _Blob]] = []
        used_blobs: set[int] = set()
        for i, j in zip(rows, cols, strict=False):
            if cost[i, j] >= FORBID:
                continue
            matched.append((tracks[i].id, blobs[j]))
            used_blobs.add(j)
        for j, b in enumerate(blobs):
            if j not in used_blobs:
                matched.append((self._birth(ts, b), b))
        return matched

    def _birth(self, ts: datetime, blob: _Blob) -> int:
        tid = next(self._ids)
        self._tracks[tid] = _Track(
            id=tid, born_ts=ts, last_ts=ts, lon=blob.centroid[0], lat=blob.centroid[1]
        )
        return tid

    def _advance_motion(self, track: _Track, ts: datetime, blob: _Blob) -> None:
        lon, lat = blob.centroid
        dt_h = (ts - track.last_ts).total_seconds() / 3600.0
        if dt_h > 0:
            mean_lat = math.radians((lat + track.lat) / 2.0)
            east_km = (lon - track.lon) * KM_PER_DEG_LAT * math.cos(mean_lat)
            north_km = (lat - track.lat) * KM_PER_DEG_LAT
            ve, vn = east_km / dt_h, north_km / dt_h
            if track.vel_e is None:
                track.vel_e, track.vel_n = ve, vn
            else:
                a = 0.5
                track.vel_e = a * ve + (1 - a) * track.vel_e
                track.vel_n = a * vn + (1 - a) * track.vel_n
        track.last_ts, track.lon, track.lat = ts, lon, lat

    def _motion(self, track: _Track) -> Motion | None:
        if track.vel_e is None or track.vel_n is None:
            return None
        speed = math.hypot(track.vel_e, track.vel_n)
        if speed < 1.0:
            return Motion(speed_kmh=round(speed, 1), bearing_deg=0.0)
        bearing = (math.degrees(math.atan2(track.vel_e, track.vel_n)) + 360.0) % 360.0
        return Motion(speed_kmh=round(speed, 1), bearing_deg=round(bearing, 1))

    def _cone(
        self, lon: float, lat: float, bearing: float, radius_km: float, half_deg: float
    ) -> dict:
        """A circular sector centred on the motion bearing, apex at the centroid."""
        from .geo import destination

        pts = [(lon, lat)]
        steps = 8
        for k in range(steps + 1):
            b = bearing - half_deg + (2 * half_deg) * k / steps
            pts.append(destination(lon, lat, b, radius_km))
        pts.append((lon, lat))
        return {"type": "Polygon", "coordinates": [pts]}

    def _dbz_sustained(self, track: _Track, ts: datetime) -> bool:
        """Has the core held ≥ `supercell_dbz_min` over the recent window?"""
        window = self._s.supercell_dbz_window_s
        recent = [d for (t, d) in track.dbz_hist if (ts - t).total_seconds() <= window]
        if len(recent) < 3:
            return False
        return float(np.median(recent)) >= self._s.supercell_dbz_min

    def _supercell(
        self,
        track: _Track,
        ts: datetime,
        motion: Motion | None,
        rate: float,
        flow: tuple[float | None, float | None] | None,
    ) -> float | None:
        """Signed motion deviation from the mean flow if the cell qualifies, else None."""
        if (ts - track.born_ts).total_seconds() < self._s.supercell_min_life_s:
            return None
        if motion is None or motion.speed_kmh < self._s.supercell_min_speed_kmh:
            return None
        if rate < self._s.supercell_lightning_min:
            return None
        if not self._dbz_sustained(track, ts):
            return None
        if flow is None:
            return None
        flow_ms, flow_dir = flow
        if flow_ms is None or flow_dir is None or flow_ms < self._s.supercell_min_flow_ms:
            return None
        dev = signed_deviation_deg(motion.bearing_deg, flow_dir)
        if abs(dev) < self._s.supercell_deviation_deg:
            return None
        return dev

    def _trend(self, track: _Track, current: float) -> str:
        if len(track.dbz_hist) < 3:
            return "steady"
        past = track.dbz_hist[0][1]
        if current - past >= 2.0:
            return "up"
        if past - current >= 2.0:
            return "down"
        return "steady"

    def _severity(self, blob: _Blob, rate: float, trend: str, cape: float | None) -> int:
        s = self._s
        trend_bonus = {"up": 1.0, "steady": 0.5, "down": 0.0}[trend]
        score = (
            s.sev_w_dbz * _norm(blob.max_dbz, s.sev_dbz_lo, s.sev_dbz_hi)
            + s.sev_w_lightning * _norm(rate, 0.0, s.sev_lightning_hi)
            + s.sev_w_area * _norm(blob.area_km2, s.sev_area_lo, s.sev_area_hi)
            + s.sev_w_trend * trend_bonus
            + s.sev_w_cape * _norm(cape or 0.0, s.sev_cape_lo, s.sev_cape_hi)
        )
        return int(round(_clamp01(score / 100.0) * 100))

    def _snapshot(
        self,
        track: _Track,
        ts: datetime,
        blob: _Blob,
        clusters: list[LightningCluster],
        cape: float | None,
        cape_at: Callable[[float, float], float | None] | None,
        flow_at: Callable[[float, float], tuple[float | None, float | None]] | None,
        user: tuple[float, float] | None,
    ) -> CellSnapshot:
        lon, lat = blob.centroid
        motion = self._motion(track)
        trend = self._trend(track, blob.max_dbz)
        local_cape = cape_at(lon, lat) if cape_at is not None else cape

        rate, flags = 0.0, []
        best = None
        for cl in clusters:
            d = haversine_km(lon, lat, cl.centroid[0], cl.centroid[1])
            if d < 15.0 and (best is None or d < best[0]):
                best = (d, cl)
        if best is not None:
            rate = best[1].rate_min
            if best[1].jump:
                flags.append("lightning_jump")

        severity = self._severity(blob, rate, trend, local_cape)
        track.sev_hist.append((ts, severity))
        track.spark_hist.append(severity)

        flow = flow_at(lon, lat) if flow_at is not None else None
        deviation = self._supercell(track, ts, motion, rate, flow)
        if deviation is not None:
            flags.append("possible_supercell")

        cones: list[dict] = []
        eta_user_min: float | None = None
        if motion is not None and motion.speed_kmh >= 1.0:
            r30 = motion.speed_kmh * 0.5
            r60 = motion.speed_kmh * 1.0
            cone30 = self._cone(lon, lat, motion.bearing_deg, r30, self._s.cone_halfangle_30_deg)
            cone60 = self._cone(lon, lat, motion.bearing_deg, r60, self._s.cone_halfangle_60_deg)
            cones = [cone30, cone60]
            if user is not None:
                up = Point(user[0], user[1])
                if Polygon(cone60["coordinates"][0]).contains(up) or Polygon(
                    cone30["coordinates"][0]
                ).contains(up):
                    dist = haversine_km(lon, lat, user[0], user[1])
                    eta_user_min = round(dist / motion.speed_kmh * 60.0, 1)

        return CellSnapshot(
            id=track.id,
            ts=ts,
            polygon=blob.polygon,
            centroid=(round(lon, 5), round(lat, 5)),
            area_km2=round(blob.area_km2, 1),
            max_dbz=round(blob.max_dbz, 1),
            motion=motion,
            severity=severity,
            lightning_rate_min=round(rate, 1),
            cape=round(local_cape, 1) if local_cape is not None else None,
            motion_deviation_deg=round(deviation, 1) if deviation is not None else None,
            trend=trend,  # type: ignore[arg-type]
            forecast_cones=cones,
            eta_user_min=eta_user_min,
            flags=flags,
            sev_series=list(track.spark_hist),
        )

    def track_severity_drop(self, cell_id: int, window_s: float) -> float | None:
        """Fractional severity drop of a cell over `window_s` (for CELL_WEAKENING)."""
        tr = self._tracks.get(cell_id)
        if tr is None or len(tr.sev_hist) < 2:
            return None
        now_ts, now_sev = tr.sev_hist[-1]
        past = [sv for (t, sv) in tr.sev_hist if (now_ts - t).total_seconds() <= window_s]
        peak = max(past) if past else now_sev
        if peak <= 0:
            return None
        return (peak - now_sev) / peak


def eta_on_user(cell: CellSnapshot, user: tuple[float, float]) -> float | None:
    """Minutes until `cell` reaches the user, if the user sits inside its cone."""
    if cell.motion is None or cell.motion.speed_kmh < 1.0 or not cell.forecast_cones:
        return None
    up = Point(user[0], user[1])
    inside = any(Polygon(cone["coordinates"][0]).contains(up) for cone in cell.forecast_cones)
    if not inside:
        return None
    dist = haversine_km(cell.centroid[0], cell.centroid[1], user[0], user[1])
    return round(dist / cell.motion.speed_kmh * 60.0, 1)


def refresh_dynamic(
    cells: list[CellSnapshot],
    clusters: list[LightningCluster],
    user: tuple[float, float] | None,
) -> None:
    """Between radar frames, refresh the fast-moving fields on held cells in place."""
    for c in cells:
        best = None
        for cl in clusters:
            d = haversine_km(c.centroid[0], c.centroid[1], cl.centroid[0], cl.centroid[1])
            if d < 15.0 and (best is None or d < best[0]):
                best = (d, cl)
        c.lightning_rate_min = round(best[1].rate_min, 1) if best else 0.0
        has_jump = best is not None and best[1].jump
        flags = [f for f in c.flags if f != "lightning_jump"]
        if has_jump:
            flags.append("lightning_jump")
        c.flags = flags
        c.eta_user_min = eta_on_user(c, user) if user is not None else None


def label_for(cell: CellSnapshot) -> str:
    """Compact map label: `#3 · 58 dBZ · 41 f/min`."""
    parts = [f"#{cell.id}", f"{cell.max_dbz:.0f} dBZ"]
    if cell.lightning_rate_min > 0:
        parts.append(f"{cell.lightning_rate_min:.0f} f/min")
    if cell.motion is not None and cell.motion.speed_kmh >= 1.0:
        parts.append(f"{compass_it(cell.motion.bearing_deg)} {cell.motion.speed_kmh:.0f}")
    return " · ".join(parts)
