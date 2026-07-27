"""Sightline visibility: solar position, light regime, rain on the line of sight."""

from __future__ import annotations

import datetime as dt

from app.models import CellSnapshot, Motion
from app.processing.geo import destination
from app.processing.sun import light_regime, solar_position
from app.routing.visibility import (
    BACKLIT_COST_KM,
    ViewProbe,
    rain_on_sight,
    sight_penalty_km,
    view_quality,
)

UTC = dt.UTC
PROBE = ViewProbe(step_km=0.5, standoff_km=4.0, threshold_mmh=2.0)


def make_cell(centroid: tuple[float, float] = (8.62, 44.71)) -> CellSnapshot:
    return CellSnapshot(
        id=7,
        ts=dt.datetime.now(UTC),
        polygon={},
        centroid=centroid,
        area_km2=140.0,
        max_dbz=57.0,
        motion=Motion(speed_kmh=35.0, bearing_deg=90.0),
        severity=80,
    )


def test_solar_noon_elevation_matches_theory() -> None:
    sun = solar_position(dt.datetime(2026, 6, 21, 11, 10, tzinfo=UTC), 12.5, 41.9)
    assert abs(sun.elevation_deg - (90.0 - 41.9 + 23.44)) < 0.5
    assert abs(sun.azimuth_deg - 180.0) < 3.0


def test_winter_solstice_elevation_matches_theory() -> None:
    sun = solar_position(dt.datetime(2026, 12, 21, 11, 10, tzinfo=UTC), 12.5, 41.9)
    assert abs(sun.elevation_deg - (90.0 - 41.9 - 23.44)) < 0.5


def test_sun_is_below_the_horizon_at_night() -> None:
    sun = solar_position(dt.datetime(2026, 7, 15, 23, 0, tzinfo=UTC), 9.19, 45.46)
    assert sun.elevation_deg < -6.0
    assert light_regime(sun, 90.0) == "notte"


def test_light_regime_splits_backlit_from_frontlit() -> None:
    sun = solar_position(dt.datetime(2026, 7, 15, 17, 0, tzinfo=UTC), 9.19, 45.46)
    assert light_regime(sun, sun.azimuth_deg) == "controluce"
    assert light_regime(sun, (sun.azimuth_deg + 180.0) % 360.0) == "illuminata"
    assert light_regime(sun, (sun.azimuth_deg + 75.0) % 360.0) == "laterale"


def _dry(_lon: float, _lat: float) -> float:
    return 0.0


def _soaked(_lon: float, _lat: float) -> float:
    return 30.0


def _no_grid(_lon: float, _lat: float) -> float | None:
    return None


def test_dry_sightline_is_not_blocked() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    rain = rain_on_sight(observer, cell, _dry, PROBE)
    assert rain.blocked_km == 0.0
    assert rain.peak_mmh == 0.0
    assert rain.samples > 0


def test_rain_between_observer_and_cell_is_measured() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    rain = rain_on_sight(observer, cell, _soaked, PROBE)
    assert 15.0 <= rain.blocked_km <= 16.5
    assert rain.peak_mmh == 30.0


def test_standoff_keeps_the_cell_itself_out_of_the_count() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 3.0)
    assert rain_on_sight(observer, cell, _soaked, PROBE).blocked_km == 0.0


def test_missing_grid_reports_no_samples() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    assert rain_on_sight(observer, cell, _no_grid, PROBE).samples == 0


def test_rain_costs_detour_kilometres() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    dry_cost = sight_penalty_km(observer, cell, PROBE, _dry, None)
    wet_cost = sight_penalty_km(observer, cell, PROBE, _soaked, None)
    assert dry_cost == 0.0
    assert wet_cost > 30.0


def test_backlit_position_costs_more_than_frontlit() -> None:
    cell = make_cell()
    when = dt.datetime(2026, 7, 15, 17, 0, tzinfo=UTC)
    sun = solar_position(when, 8.62, 44.71)
    toward_sun = destination(8.62, 44.71, (sun.azimuth_deg + 180.0) % 360.0, 15.0)
    away_from_sun = destination(8.62, 44.71, sun.azimuth_deg, 15.0)
    assert sight_penalty_km(toward_sun, cell, PROBE, None, sun) == BACKLIT_COST_KM
    assert sight_penalty_km(away_from_sun, cell, PROBE, None, sun) == 0.0


def test_view_quality_reports_clear_and_blocked() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    when = dt.datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    clear = view_quality(observer, cell, PROBE, rain_at=_dry, now=when)
    assert clear["rain_blocked_km"] == 0.0
    assert "vista libera" in clear["text"]
    assert clear["quality"] in {"buona", "media"}

    blocked = view_quality(observer, cell, PROBE, rain_at=_soaked, now=when)
    assert blocked["rain_blocked_km"] > 10.0
    assert blocked["quality"] == "scarsa"
    assert "vista chiusa" in blocked["text"]


def test_view_quality_is_none_when_standing_on_the_cell() -> None:
    cell = make_cell()
    assert view_quality(cell.centroid, cell, PROBE, rain_at=_dry) is None


def test_view_quality_flags_unknown_rain() -> None:
    cell = make_cell()
    observer = destination(8.62, 44.71, 180.0, 20.0)
    for sampler in (None, _no_grid):
        out = view_quality(observer, cell, PROBE, rain_at=sampler)
        assert out["rain_known"] is False
        assert out["rain_blocked_km"] == 0.0
        assert "non nota" in out["text"]
