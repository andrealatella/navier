"""Offline PMTiles basemap endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.rest as rest_mod
from app.config import Settings
from app.main import app

client = TestClient(app)


def _use_pmtiles(monkeypatch, tmp_path, blob: bytes | None) -> None:
    path = tmp_path / "basemap.pmtiles"
    if blob is not None:
        path.write_bytes(blob)
    monkeypatch.setattr(rest_mod, "settings", Settings(basemap_pmtiles=str(path)))


def test_basemap_absent(monkeypatch, tmp_path):
    _use_pmtiles(monkeypatch, tmp_path, None)
    j = client.get("/api/basemap").json()
    assert j["available"] is False and j["url"] is None
    assert client.get("/api/basemap.pmtiles").status_code == 404


def test_basemap_present_and_range(monkeypatch, tmp_path):
    blob = bytes(range(256)) * 8
    _use_pmtiles(monkeypatch, tmp_path, blob)

    j = client.get("/api/basemap").json()
    assert j["available"] is True
    assert j["url"] == "/api/basemap.pmtiles"
    assert j["size_bytes"] == len(blob)

    r = client.get("/api/basemap.pmtiles", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == blob[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(blob)}"
