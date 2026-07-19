"""gpsd TPV parser tests."""

from __future__ import annotations

from app.ingest.gpsd import parse_tpv


def test_parse_full_3d_fix() -> None:
    obj = {
        "class": "TPV",
        "device": "/dev/ttyUSB0",
        "mode": 3,
        "lat": 45.070312,
        "lon": 7.686856,
        "alt": 250.0,
        "track": 10.4,
        "speed": 12.5,
    }
    pos = parse_tpv(obj)
    assert pos is not None
    assert pos.source == "gpsd"
    assert round(pos.lat, 4) == 45.0703
    assert round(pos.lon, 4) == 7.6869
    assert pos.speed_kmh == 45.0
    assert pos.heading_deg == 10.4


def test_no_fix_returns_none() -> None:
    assert parse_tpv({"class": "TPV", "mode": 1, "lat": 1.0, "lon": 2.0}) is None
    assert parse_tpv({"class": "TPV", "mode": 0}) is None


def test_missing_coords_returns_none() -> None:
    assert parse_tpv({"class": "TPV", "mode": 3, "lat": 45.0}) is None


def test_non_tpv_class_ignored() -> None:
    assert parse_tpv({"class": "SKY", "satellites": []}) is None


def test_speed_and_track_optional() -> None:
    pos = parse_tpv({"class": "TPV", "mode": 2, "lat": 45.0, "lon": 7.0})
    assert pos is not None
    assert pos.speed_kmh is None
    assert pos.heading_deg is None
