"""Snapshot builder: compactness, cell cap/order, distances, optional context."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.copilot.snapshot import MAX_CELLS, build_snapshot
from app.models import CellSnapshot, Motion, UserPosition
from app.processing.world import WorldState

NOW = datetime(2026, 7, 13, 15, 42, tzinfo=UTC)


def _poly(lon: float, lat: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[lon, lat], [lon + 0.1, lat], [lon, lat + 0.1], [lon, lat]]],
    }


def _cell(cid: int, *, lon=8.6, lat=45.0, sev=50, dbz=55.0) -> CellSnapshot:
    return CellSnapshot(
        id=cid,
        ts=NOW,
        polygon=_poly(lon, lat),
        centroid=(lon, lat),
        area_km2=100,
        max_dbz=dbz,
        motion=Motion(speed_kmh=35, bearing_deg=110),
        severity=sev,
        lightning_rate_min=41,
        trend="up",
        flags=["lightning_jump"],
    )


def _user() -> UserPosition:
    return UserPosition(ts=NOW, lat=44.71, lon=8.62, speed_kmh=74, heading_deg=315, source="phone")


def test_snapshot_is_compact_and_shaped():
    ws = WorldState(
        ts=NOW,
        cells=[_cell(3)],
        user=_user(),
        radar_age_s=140,
        lightning_age_s=3,
        cape=2100,
        dpc_alert_level="arancione",
    )
    snap = build_snapshot(
        ws, target_cell_id=3, alerts_active=[{"rule_id": "HAIL_RISK", "priority": 1}]
    )
    blob = json.dumps(snap, ensure_ascii=False)
    assert len(blob.encode("utf-8")) < 2048
    assert snap["user"]["moving"] is True
    assert snap["meteo_local"] == {"cape": 2100, "allerta_dpc": "arancione"}
    c = snap["cells"][0]
    assert c["id"] == 3 and c["dist_km"] > 0 and c["bearing"] in {"N", "NE", "NO"}
    assert c["motion"]["verso"] == "E"
    assert snap["alerts_active"] == ["HAIL_RISK (P1)"]
    assert snap["target"]["cell_id"] == 3
    assert snap["data_age_s"] == {"radar": 140, "lightning": 3}


def test_cells_capped_and_severity_ordered():
    cells = [_cell(i, sev=i * 5, lon=8.0 + i * 0.1) for i in range(1, 12)]
    ws = WorldState(ts=NOW, cells=cells, user=_user())
    snap = build_snapshot(ws)
    assert len(snap["cells"]) == MAX_CELLS
    sevs = [c["severity"] for c in snap["cells"]]
    assert sevs == sorted(sevs, reverse=True)


def test_no_user_omits_distance_and_user():
    ws = WorldState(ts=NOW, cells=[_cell(3)], user=None)
    snap = build_snapshot(ws)
    assert "user" not in snap
    assert "dist_km" not in snap["cells"][0]
    assert "bearing" not in snap["cells"][0]


def test_absent_context_is_dropped():
    ws = WorldState(ts=NOW, cells=[], user=None)
    snap = build_snapshot(ws)
    assert "meteo_local" not in snap
    assert "alerts_active" not in snap
    assert "target" not in snap
    assert snap["cells"] == []
