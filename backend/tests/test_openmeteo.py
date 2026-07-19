"""Open-Meteo ingestor + MeteoStore tests."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app.ingest.openmeteo import flow_series, grid_coords, mean_flow, shear_ms, shear_series
from app.store.meteo import MeteoPoint, MeteoStore


def test_shear_opposite_winds_adds():
    s = shear_ms(30.0, 270.0, 5.0, 90.0)
    assert s == 35.0


def test_shear_same_wind_is_zero():
    assert shear_ms(20.0, 200.0, 20.0, 200.0) == 0.0


def test_shear_perpendicular():
    s = shear_ms(10.0, 0.0, 0.0, 0.0)
    assert math.isclose(s, 10.0, abs_tol=1e-6)


def test_shear_none_inputs_safe():
    assert shear_ms(None, 10.0, 5.0, 90.0) == 0.0


def test_shear_series_length_matches_shortest():
    hourly = {
        "wind_speed_500hPa": [30.0, 25.0, 20.0],
        "wind_direction_500hPa": [270.0, 260.0, 250.0],
        "wind_speed_10m": [5.0, 4.0],
        "wind_direction_10m": [90.0, 90.0],
    }
    series = shear_series(hourly)
    assert len(series) == 2
    assert series[0] == 35.0




def test_mean_flow_same_wind_both_levels():
    flow = mean_flow(20.0, 270.0, 20.0, 270.0)
    assert flow is not None
    speed, bearing = flow
    assert math.isclose(speed, 20.0, abs_tol=1e-6)
    assert math.isclose(bearing, 90.0, abs_tol=1e-6)


def test_mean_flow_averages_as_vectors_across_north():
    flow = mean_flow(10.0, 350.0, 10.0, 10.0)
    assert flow is not None
    speed, bearing = flow
    assert math.isclose(bearing, 180.0, abs_tol=1e-6)
    assert speed < 10.0


def test_mean_flow_opposing_levels_cancel():
    flow = mean_flow(15.0, 90.0, 15.0, 270.0)
    assert flow is not None
    assert math.isclose(flow[0], 0.0, abs_tol=1e-6)


def test_mean_flow_missing_level_is_none():
    assert mean_flow(None, 270.0, 20.0, 270.0) is None
    assert mean_flow(20.0, 270.0, 20.0, None) is None


def test_flow_series_length_matches_shortest():
    hourly = {
        "wind_speed_700hPa": [10.0, 12.0, 14.0],
        "wind_direction_700hPa": [270.0, 270.0, 270.0],
        "wind_speed_500hPa": [20.0, 22.0],
        "wind_direction_500hPa": [270.0, 270.0],
    }
    speeds, bearings = flow_series(hourly)
    assert len(speeds) == 2 and len(bearings) == 2
    assert math.isclose(speeds[0], 15.0, abs_tol=1e-6)
    assert math.isclose(bearings[0], 90.0, abs_tol=1e-6)


def test_flow_series_missing_block_is_empty():
    assert flow_series({}) == ([], [])


def test_grid_coords_regular_and_covers_bbox():
    coords = grid_coords(5.5, 20.5, 35.0, 48.5, 0.5)
    lats = {c[0] for c in coords}
    lons = {c[1] for c in coords}
    assert (35.0, 5.5) in coords
    assert (48.5, 20.5) in coords
    assert all(abs((lat / 0.5) - round(lat / 0.5)) < 1e-9 for lat in lats)
    assert all(abs((lon / 0.5) - round(lon / 0.5)) < 1e-9 for lon in lons)


def _store_with_grid() -> MeteoStore:
    store = MeteoStore(step_deg=0.5)
    times = ["2026-07-14T12:00", "2026-07-14T13:00", "2026-07-14T14:00"]
    points = [
        MeteoPoint(
            lat=44.5,
            lon=8.5,
            cape=[100.0, 1800.0, 2200.0],
            shear_ms=[10.0, 18.0, 22.0],
            flow_ms=[8.0, 14.0, 16.0],
            flow_dir=[60.0, 70.0, 75.0],
        ),
        MeteoPoint(lat=45.0, lon=9.0, cape=[0.0, 50.0, 60.0], shear_ms=[5.0, 6.0, 7.0]),
    ]
    store.set(times, points)
    return store


def test_store_sample_nearest_node():
    store = _store_with_grid()
    cape, shear = store.sample(8.62, 44.71, hour_index=1)
    assert cape == 1800.0
    assert shear == 18.0


def test_store_sample_default_hour_picks_nearest_time():
    store = _store_with_grid()
    now = datetime(2026, 7, 14, 13, 20, tzinfo=UTC)
    assert store.hour_index(now) == 1


def test_store_sample_empty_returns_none():
    store = MeteoStore()
    assert store.sample(9.0, 45.0) == (None, None)


def test_store_sample_flow_nearest_node():
    store = _store_with_grid()
    speed, bearing = store.sample_flow(8.62, 44.71, hour_index=1)
    assert speed == 14.0 and bearing == 70.0


def test_store_sample_flow_without_flow_series_is_none():
    store = _store_with_grid()
    assert store.sample_flow(9.0, 45.0, hour_index=1) == (None, None)


def test_store_sample_flow_empty_returns_none():
    assert MeteoStore().sample_flow(9.0, 45.0) == (None, None)


def test_store_heatmap_shape():
    store = _store_with_grid()
    hm = store.heatmap(hour_index=2)
    assert hm["hour"] == "2026-07-14T14:00"
    assert hm["hours"] == store.times
    assert hm["max_cape"] == 2200
    fc = hm["grid"]
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    props = fc["features"][0]["properties"]
    assert props["cape"] == 2200 and props["shear"] == 22.0


def test_store_heatmap_clamps_out_of_range_hour():
    store = _store_with_grid()
    hm = store.heatmap(hour_index=99)
    assert hm["hour_index"] == 2
