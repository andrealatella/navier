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
from app.routing.intercept import intercept_point, maps_deeplink, route_crosses_cones
from app.routing.ors import OrsProvider
from app.routing.osrm import OsrmProvider

UTC = dt.UTC


def make_cell(cell_id: int = 3, *, motion: Motion | None, cone: dict | None = None) -> CellSnapshot:
    return CellSnapshot(
        id=cell_id,
        ts=dt.datetime.now(UTC),
        polygon={},
        centroid=(8.62, 44.71),
        area_km2=120.0,
        max_dbz=58.0,
        motion=motion,
        severity=82,
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
