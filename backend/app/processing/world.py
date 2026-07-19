"""WorldState: the single fused snapshot of the situation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models import CellSnapshot, LightningCluster, UserPosition
from .geo import compass_it


@dataclass
class WorldState:
    """One fused view of the world at time `ts`."""

    ts: datetime
    cells: list[CellSnapshot] = field(default_factory=list)
    clusters: list[LightningCluster] = field(default_factory=list)
    user: UserPosition | None = None
    nearest_strike_km: float | None = None
    radar_age_s: float | None = None
    lightning_age_s: float | None = None
    cape: float | None = None
    shear_ms: float | None = None
    local_sri_mmh: float | None = None
    dpc_alert_level: str | None = None
    target_cell_id: int | None = None
    target_severity_drop: float | None = None

    def cell(self, cell_id: int) -> CellSnapshot | None:
        return next((c for c in self.cells if c.id == cell_id), None)


def _cells_fc(cells: list[CellSnapshot]) -> dict:
    """FeatureCollection of cell polygons with drawing/label properties."""
    from .cells import label_for

    feats = []
    for c in cells:
        if not c.polygon:
            continue
        feats.append(
            {
                "type": "Feature",
                "geometry": c.polygon,
                "properties": {
                    "id": c.id,
                    "max_dbz": c.max_dbz,
                    "severity": c.severity,
                    "lightning_min": c.lightning_rate_min,
                    "cape": round(c.cape) if c.cape is not None else None,
                    "poh": round(c.poh) if c.poh is not None else None,
                    "trend": c.trend,
                    "speed_kmh": c.motion.speed_kmh if c.motion else None,
                    "bearing_deg": c.motion.bearing_deg if c.motion else None,
                    "deviation_deg": c.motion_deviation_deg,
                    "eta_min": c.eta_user_min,
                    "flags": c.flags,
                    "sev_series": c.sev_series,
                    "label": label_for(c),
                    "centroid": list(c.centroid),
                },
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def _cones_fc(cells: list[CellSnapshot]) -> dict:
    """FeatureCollection of +30/+60 forecast cones (dashed on the map)."""
    feats = []
    for c in cells:
        for horizon, cone in zip((30, 60), c.forecast_cones, strict=False):
            feats.append(
                {
                    "type": "Feature",
                    "geometry": cone,
                    "properties": {"id": c.id, "horizon": horizon, "severity": c.severity},
                }
            )
    return {"type": "FeatureCollection", "features": feats}


def _vectors_fc(cells: list[CellSnapshot]) -> dict:
    """FeatureCollection of motion arrows (centroid → ~15 min ahead)."""
    from .geo import destination

    feats = []
    for c in cells:
        if c.motion is None or c.motion.speed_kmh < 1.0:
            continue
        lon, lat = c.centroid
        ahead = destination(lon, lat, c.motion.bearing_deg, c.motion.speed_kmh * 0.25)
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon, lat], list(ahead)]},
                "properties": {"id": c.id, "bearing_deg": c.motion.bearing_deg},
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def to_wire(ws: WorldState, alerts: list[dict]) -> dict:
    """The `world_state` WS payload: GeoJSON layers + compact state."""
    user = None
    if ws.user is not None:
        user = {
            "lat": round(ws.user.lat, 5),
            "lon": round(ws.user.lon, 5),
            "speed_kmh": ws.user.speed_kmh,
            "heading_deg": ws.user.heading_deg,
            "source": ws.user.source,
        }
    return {
        "t": int(ws.ts.timestamp() * 1000),
        "cells": _cells_fc(ws.cells),
        "cones": _cones_fc(ws.cells),
        "vectors": _vectors_fc(ws.cells),
        "clusters": [
            {
                "id": cl.id,
                "lon": cl.centroid[0],
                "lat": cl.centroid[1],
                "count": cl.count,
                "rate_min": cl.rate_min,
                "jump": cl.jump,
            }
            for cl in ws.clusters
        ],
        "user": user,
        "data_age_s": {"radar": ws.radar_age_s, "lightning": ws.lightning_age_s},
        "alerts_active": alerts,
    }


def cell_summaries(ws: WorldState) -> list[dict]:
    """Compact per-cell rows for the copilot snapshot / debug (kept small)."""
    rows = []
    for c in ws.cells:
        rows.append(
            {
                "id": c.id,
                "max_dbz": c.max_dbz,
                "severity": c.severity,
                "lightning_min": c.lightning_rate_min,
                "trend": c.trend,
                "verso": compass_it(c.motion.bearing_deg) if c.motion else None,
                "eta_user_min": c.eta_user_min,
                "flags": c.flags,
            }
        )
    return rows
