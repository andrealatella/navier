"""Cell tracker tests on synthetic frames."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("scipy", reason="processing extra not installed")
pytest.importorskip("shapely", reason="processing extra not installed")
pytest.importorskip("rasterio", reason="processing extra not installed")

import numpy as np  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import Transformer  # noqa: E402

from app.config import settings  # noqa: E402
from app.processing.cells import CellTracker  # noqa: E402

RES = 1000.0
SIZE = 180
_T = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_X0, _Y0 = _T.transform(8.0, 46.0)
TRANSFORM = Affine(RES, 0.0, _X0, 0.0, -RES, _Y0)

T0 = datetime(2026, 7, 12, 15, 0, tzinfo=UTC)


def frame() -> np.ndarray:
    return np.zeros((SIZE, SIZE), dtype=np.float32)


def blob(grid: np.ndarray, col: float, row: float, peak: float, radius: float = 13.0) -> None:
    """Add a Gaussian reflectivity blob centred at pixel (col, row)."""
    rr, cc = np.mgrid[0:SIZE, 0:SIZE]
    d2 = (cc - col) ** 2 + (rr - row) ** 2
    grid[:] = np.maximum(grid, peak * np.exp(-d2 / (2 * radius**2))).astype(np.float32)


def ids_at(cells) -> set[int]:
    return {c.id for c in cells}


def test_single_cell_is_born_and_kept_stable():
    tr = CellTracker(settings)
    g = frame()
    blob(g, 90, 90, 58)
    cells0 = tr.update(T0, g, TRANSFORM)
    assert len(cells0) == 1
    cid = cells0[0].id
    assert cells0[0].max_dbz >= 55

    cells1 = tr.update(T0 + timedelta(minutes=5), g.copy(), TRANSFORM)
    assert ids_at(cells1) == {cid}


def test_weak_or_tiny_echo_is_not_a_cell():
    tr = CellTracker(settings)
    g = frame()
    blob(g, 90, 90, 42, radius=13)
    assert tr.update(T0, g, TRANSFORM) == []

    g2 = frame()
    blob(g2, 90, 90, 60, radius=2.0)
    assert tr.update(T0, g2, TRANSFORM) == []


def test_moving_cell_keeps_id_and_gets_motion():
    tr = CellTracker(settings)
    cid = None
    ids_seen: list[set[int]] = []
    last = None
    for k in range(5):
        g = frame()
        blob(g, 60 + 5 * k, 90, 57)
        last = tr.update(T0 + timedelta(minutes=5 * k), g, TRANSFORM)
        assert len(last) == 1
        ids_seen.append(ids_at(last))
        cid = last[0].id

    assert all(s == {cid} for s in ids_seen)
    motion = last[0].motion
    assert motion is not None and motion.speed_kmh > 0
    assert 60 <= motion.bearing_deg <= 120
    assert len(last[0].forecast_cones) == 2


def test_two_cells_merge_biggest_inherits_id():
    tr = CellTracker(settings)
    g = frame()
    blob(g, 55, 90, 57, radius=15)
    blob(g, 125, 90, 55, radius=13)
    cells0 = tr.update(T0, g, TRANSFORM)
    assert len(cells0) == 2

    ts = T0
    merged = None
    for k in range(1, 6):
        ts = T0 + timedelta(minutes=5 * k)
        g = frame()
        blob(g, 55 + 8 * k, 90, 57, radius=15)
        blob(g, 125 - 6 * k, 90, 55, radius=13)
        merged = tr.update(ts, g, TRANSFORM)
        if len(merged) == 1:
            break
    assert merged is not None and len(merged) == 1
    assert merged[0].id in {c.id for c in cells0}


def test_cell_dies_after_max_misses():
    tr = CellTracker(settings)
    g = frame()
    blob(g, 90, 90, 58)
    born = tr.update(T0, g, TRANSFORM)
    cid = born[0].id

    empty = frame()
    for k in range(1, settings.track_max_misses + 2):
        out = tr.update(T0 + timedelta(minutes=5 * k), empty.copy(), TRANSFORM)
        assert cid not in ids_at(out)
    g2 = frame()
    blob(g2, 90, 90, 58)
    reborn = tr.update(T0 + timedelta(minutes=5 * (settings.track_max_misses + 3)), g2, TRANSFORM)
    assert reborn and cid not in ids_at(reborn)


def test_polygon_and_centroid_are_geographic():
    tr = CellTracker(settings)
    g = frame()
    blob(g, 90, 90, 58)
    c = tr.update(T0, g, TRANSFORM)[0]
    lon, lat = c.centroid
    assert 6.0 < lon < 12.0 and 43.0 < lat < 46.5
    assert c.polygon["type"] == "Polygon"
    ring = c.polygon["coordinates"][0]
    assert len(ring) >= 4
