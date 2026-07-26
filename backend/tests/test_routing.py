"""Routing tests: intercept geometry, cone crossing, provider parsing, endpoint."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.api import rest
from app.config import settings
from app.main import app
from app.models import CellSnapshot, Motion, UserPosition
from app.routing import ors as ors_mod
from app.routing import osrm as osrm_mod
from app.routing.base import Route, RoutingProvider
from app.routing.intercept import (
    cell_eta_to_point_min,
    feasibility,
    inflow_flank,
    intercept_point,
    maps_deeplink,
    road_intercept_point,
    route_crosses_cones,
)
from app.routing.ors import OrsProvider
from app.routing.osrm import OsrmProvider

UTC = dt.UTC


def make_cell(
    cell_id: int = 3,
    *,
    motion: Motion | None,
    cone: dict | None = None,
    deviation: float | None = None,
) -> CellSnapshot:
    return CellSnapshot(
        id=cell_id,
        ts=dt.datetime.now(UTC),
        polygon={},
        centroid=(8.62, 44.71),
        area_km2=120.0,
        max_dbz=58.0,
        motion=motion,
        severity=82,
        motion_deviation_deg=deviation,
        forecast_cones=[cone] if cone else [],
    )




def test_maps_deeplink() -> None:
    url = maps_deeplink(44.71, 8.62)
    assert url.startswith("https://www.google.com/maps/dir/?api=1")
    assert "destination=44.710000,8.620000" in url
    assert "travelmode=driving" in url


def test_intercept_moving_cell_is_offset_from_centroid() -> None:
    cell = make_cell(motion=Motion(speed_kmh=35.0, bearing_deg=110.0))
    (lon, lat), is_intercept, note = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)
    assert is_intercept is True
    assert (lon, lat) != cell.centroid
    assert "intercetto" in note


def test_intercept_stationary_cell_falls_back_to_centroid() -> None:
    cell = make_cell(motion=None)
    target, is_intercept, note = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)
    assert is_intercept is False
    assert target == cell.centroid
    assert "ferma" in note


def test_intercept_side_follows_the_user() -> None:
    """The sidestep should land on opposite sides for users on opposite flanks."""
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0))
    north_user = intercept_point(cell, (8.62, 45.2), 30.0, 8.0)[0]
    south_user = intercept_point(cell, (8.62, 44.2), 30.0, 8.0)[0]
    assert north_user[1] > cell.centroid[1]
    assert south_user[1] < cell.centroid[1]


def test_right_mover_overrides_the_user_side() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0), deviation=25.0)
    perp, why = inflow_flank(cell, (8.62, 45.2))
    assert why == "destrorsa"
    assert perp == 180.0
    target = intercept_point(cell, (8.62, 45.2), 30.0, 8.0)[0]
    assert target[1] < cell.centroid[1]


def test_left_mover_uses_the_left_flank() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0), deviation=-25.0)
    perp, why = inflow_flank(cell, (8.62, 44.2))
    assert why == "sinistrorsa"
    assert perp == 0.0
    target = intercept_point(cell, (8.62, 44.2), 30.0, 8.0)[0]
    assert target[1] > cell.centroid[1]


def test_supercell_note_mentions_the_inflow_side() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0), deviation=25.0)
    note = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)[2]
    assert "inflow" in note
    assert "destrorsa" in note


def test_cell_eta_is_signed_along_the_motion_vector() -> None:
    from app.processing.geo import destination

    cell = make_cell(motion=Motion(speed_kmh=60.0, bearing_deg=90.0))
    ahead = destination(8.62, 44.71, 90.0, 30.0)
    behind = destination(8.62, 44.71, 270.0, 30.0)
    assert abs(cell_eta_to_point_min(cell, ahead) - 30.0) < 1.0
    assert abs(cell_eta_to_point_min(cell, behind) + 30.0) < 1.0


def test_feasibility_verdicts() -> None:
    from app.processing.geo import destination

    cell = make_cell(motion=Motion(speed_kmh=60.0, bearing_deg=90.0))
    ahead = destination(8.62, 44.71, 90.0, 30.0)
    behind = destination(8.62, 44.71, 270.0, 30.0)

    assert feasibility(cell, ahead, 20.0, 5.0)["verdict"] == "in_tempo"
    assert feasibility(cell, ahead, 28.0, 5.0)["verdict"] == "limite"
    assert feasibility(cell, ahead, 45.0, 5.0)["verdict"] == "tardi"
    assert feasibility(cell, behind, 10.0, 5.0)["verdict"] == "si_allontana"
    assert feasibility(None, ahead, 10.0, 5.0) is None


def test_feasibility_none_for_stationary_cell() -> None:
    cell = make_cell(motion=None)
    assert feasibility(cell, (8.7, 44.8), 10.0, 5.0) is None


async def _snap_identity(p: tuple[float, float]) -> tuple[float, float]:
    return p


async def _snap_none(_p: tuple[float, float]) -> None:
    return None


def _snap_shift(dlon: float, dlat: float):
    async def fn(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] + dlon, p[1] + dlat)

    return fn


async def test_road_intercept_keeps_a_point_already_on_a_road() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0))
    base = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)[0]
    point, is_intercept, note = await road_intercept_point(
        cell, (8.5, 44.6), 30.0, 8.0, _snap_identity, min_core_km=5.0, max_snap_km=3.0
    )
    assert is_intercept is True
    assert point == base
    assert "su strada" in note


async def test_road_intercept_falls_back_when_nothing_snaps() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0))
    base = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)[0]
    point, _is_intercept, note = await road_intercept_point(
        cell, (8.5, 44.6), 30.0, 8.0, _snap_none, min_core_km=5.0, max_snap_km=3.0
    )
    assert point == base
    assert "geometrico" in note


async def test_road_intercept_rejects_a_far_snap() -> None:
    cell = make_cell(motion=Motion(speed_kmh=40.0, bearing_deg=90.0))
    base = intercept_point(cell, (8.5, 44.6), 30.0, 8.0)[0]
    point, _is_intercept, note = await road_intercept_point(
        cell, (8.5, 44.6), 30.0, 8.0, _snap_shift(0.5, 0.5), min_core_km=5.0, max_snap_km=3.0
    )
    assert point == base
    assert "geometrico" in note


async def test_road_intercept_skips_snapping_for_a_stationary_cell() -> None:
    cell = make_cell(motion=None)
    point, is_intercept, note = await road_intercept_point(
        cell, (8.5, 44.6), 30.0, 8.0, _snap_identity, min_core_km=5.0, max_snap_km=3.0
    )
    assert is_intercept is False
    assert point == cell.centroid
    assert "ferma" in note


def _cone(coords: list[list[float]]) -> dict:
    return {"type": "Polygon", "coordinates": [coords]}


def test_route_crosses_cone_is_detected() -> None:
    cone = _cone([[8.6, 44.8], [9.0, 44.6], [9.0, 44.9], [8.6, 44.8]])
    cell = make_cell(motion=Motion(speed_kmh=30.0, bearing_deg=110.0), cone=cone)
    through = [[8.7, 44.75], [8.8, 44.72], [8.85, 44.74]]
    assert route_crosses_cones(through, [cell]) == [3]


def test_route_away_from_cone_is_clear() -> None:
    cone = _cone([[8.6, 44.8], [9.0, 44.6], [9.0, 44.9], [8.6, 44.8]])
    cell = make_cell(motion=Motion(speed_kmh=30.0, bearing_deg=110.0), cone=cone)
    away = [[7.0, 45.6], [7.1, 45.7]]
    assert route_crosses_cones(away, [cell]) == []




class _FakeResp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict:
        return self._data


class _FakeClient:
    """Stands in for httpx.AsyncClient; returns a fixed payload for get/post."""

    def __init__(self, data: dict, **_: object) -> None:
        self._data = data

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def get(self, *_: object, **__: object) -> _FakeResp:
        return _FakeResp(self._data)

    async def post(self, *_: object, **__: object) -> _FakeResp:
        return _FakeResp(self._data)


CANNED_OSRM = {
    "code": "Ok",
    "routes": [
        {
            "distance": 57127.8,
            "duration": 3617.4,
            "geometry": {"type": "LineString", "coordinates": [[8.62, 44.71], [8.9, 45.05]]},
        }
    ],
}

CANNED_ORS = {
    "features": [
        {
            "geometry": {"type": "LineString", "coordinates": [[8.62, 44.71], [8.9, 45.05]]},
            "properties": {"summary": {"distance": 57127.8, "duration": 3617.4}},
        }
    ]
}


async def test_osrm_parses_route(monkeypatch) -> None:
    monkeypatch.setattr(osrm_mod.httpx, "AsyncClient", lambda **k: _FakeClient(CANNED_OSRM))
    prov = OsrmProvider(settings.osrm_base_url, settings.http_user_agent, 5.0)
    r = await prov.route((8.62, 44.71), (8.9, 45.05))
    assert r is not None
    assert r.provider == "osrm"
    assert r.distance_km == 57.13
    assert round(r.duration_min, 1) == 60.3
    assert r.coordinates[0] == [8.62, 44.71]


async def test_osrm_no_route_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        osrm_mod.httpx, "AsyncClient", lambda **k: _FakeClient({"code": "NoRoute", "routes": []})
    )
    prov = OsrmProvider(settings.osrm_base_url, settings.http_user_agent, 5.0)
    assert await prov.route((8.62, 44.71), (8.9, 45.05)) is None


async def test_ors_parses_route(monkeypatch) -> None:
    monkeypatch.setattr(ors_mod.httpx, "AsyncClient", lambda **k: _FakeClient(CANNED_ORS))
    prov = OrsProvider("key", settings.ors_base_url, settings.http_user_agent, 5.0)
    r = await prov.route((8.62, 44.71), (8.9, 45.05))
    assert r is not None
    assert r.provider == "ors"
    assert r.distance_km == 57.13




class _FakeProvider(RoutingProvider):
    name = "fake"

    def __init__(self, coords: list[list[float]]) -> None:
        self._coords = coords

    async def route(self, start, dest) -> Route:
        return Route("fake", 12.3, 20.0, self._coords)


class _FakeProc:
    def __init__(self, user: UserPosition | None, cells: list[CellSnapshot]) -> None:
        self._user = user
        self._cells = cells

    def current_user(self) -> UserPosition | None:
        return self._user

    def find_cell(self, cell_id: int) -> CellSnapshot | None:
        return next((c for c in self._cells if c.id == cell_id), None)

    def current_cells(self) -> list[CellSnapshot]:
        return list(self._cells)


client = TestClient(app)


def _wire_processor(monkeypatch, user, cells, route_coords) -> None:
    monkeypatch.setattr(rest.runtime, "processor", lambda: _FakeProc(user, cells))
    monkeypatch.setattr(rest, "build_provider", lambda s: _FakeProvider(route_coords))


def test_route_endpoint_intercept_flags_cone_crossing(monkeypatch) -> None:
    cone = _cone([[8.6, 44.8], [9.0, 44.6], [9.0, 44.9], [8.6, 44.8]])
    cell = make_cell(motion=Motion(speed_kmh=30.0, bearing_deg=110.0), cone=cone)
    user = UserPosition(lat=44.6, lon=8.5, source="manual")
    _wire_processor(monkeypatch, user, [cell], [[8.7, 44.75], [8.85, 44.73]])

    resp = client.post("/api/route", json={"cell_id": 3, "mode": "intercept"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "fake"
    assert body["intercept"] is True
    assert body["cell_id"] == 3
    assert body["crosses_cone_cell_ids"] == [3]
    assert body["maps_url"].startswith("https://www.google.com/maps/dir/")


def test_route_endpoint_without_position_is_409(monkeypatch) -> None:
    _wire_processor(monkeypatch, None, [], [[8.7, 44.75]])
    resp = client.post("/api/route", json={"cell_id": 3})
    assert resp.status_code == 409


def test_route_endpoint_point_destination(monkeypatch) -> None:
    user = UserPosition(lat=44.6, lon=8.5, source="manual")
    _wire_processor(monkeypatch, user, [], [[8.5, 44.6], [8.62, 44.71]])
    resp = client.post("/api/route", json={"dest_lat": 44.71, "dest_lon": 8.62})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intercept"] is False
    assert body["cell_id"] is None
    assert body["dest"] == {"lat": 44.71, "lon": 8.62}
