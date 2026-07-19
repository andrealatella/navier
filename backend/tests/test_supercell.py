"""'Possible supercell' heuristic tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("scipy", reason="processing extra not installed")
pytest.importorskip("shapely", reason="processing extra not installed")
pytest.importorskip("rasterio", reason="processing extra not installed")

import numpy as np  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import Transformer  # noqa: E402

from app.config import Settings  # noqa: E402
from app.models import LightningCluster  # noqa: E402
from app.processing.cells import CellTracker, signed_deviation_deg  # noqa: E402

RES = 1000.0
SIZE = 180
_T = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_X0, _Y0 = _T.transform(8.0, 46.0)
TRANSFORM = Affine(RES, 0.0, _X0, 0.0, -RES, _Y0)

T0 = datetime(2026, 7, 12, 15, 0, tzinfo=UTC)

FLOW_BEARING_RIGHT = 50.0
STRONG_RATE = 40.0


def frame() -> np.ndarray:
    return np.zeros((SIZE, SIZE), dtype=np.float32)


def blob(grid: np.ndarray, col: float, row: float, peak: float, radius: float = 13.0) -> None:
    """Add a Gaussian reflectivity blob centred at pixel (col, row)."""
    rr, cc = np.mgrid[0:SIZE, 0:SIZE]
    d2 = (cc - col) ** 2 + (rr - row) ** 2
    grid[:] = np.maximum(grid, peak * np.exp(-d2 / (2 * radius**2))).astype(np.float32)


def flow_const(speed_ms: float, bearing_deg: float):
    """A `flow_at` callable with the same mean flow everywhere."""
    return lambda lon, lat: (speed_ms, bearing_deg)


def run_storm(
    *,
    frames: int = 12,
    peak: float = 58.0,
    rate: float = STRONG_RATE,
    flow_at=None,
    settings: Settings | None = None,
):
    """Drive a strong cell drifting east and return its last snapshot."""
    s = settings or Settings()
    tr = CellTracker(s)
    if flow_at is None:
        flow_at = flow_const(15.0, FLOW_BEARING_RIGHT)

    last = None
    clusters: list[LightningCluster] = []
    for k in range(frames):
        g = frame()
        blob(g, 60 + 5 * k, 90, peak)
        last = tr.update(
            T0 + timedelta(minutes=5 * k),
            g,
            TRANSFORM,
            clusters=clusters,
            flow_at=flow_at,
        )
        assert len(last) == 1, "the synthetic storm must stay a single cell"
        clusters = [
            LightningCluster(id=1, centroid=last[0].centroid, count=200, rate_min=rate, jump=False)
        ]
    return last[0]




def test_deviation_right_is_positive():
    assert signed_deviation_deg(90.0, 50.0) == 40.0


def test_deviation_left_is_negative():
    assert signed_deviation_deg(50.0, 90.0) == -40.0


def test_deviation_wraps_across_north():
    assert signed_deviation_deg(10.0, 350.0) == 20.0
    assert signed_deviation_deg(350.0, 10.0) == -20.0


def test_deviation_identical_is_zero():
    assert signed_deviation_deg(123.0, 123.0) == 0.0


def test_deviation_is_bounded():
    for b in range(0, 360, 7):
        for r in range(0, 360, 11):
            assert -180.0 <= signed_deviation_deg(float(b), float(r)) < 180.0


def test_deviation_of_exact_reversal():
    assert signed_deviation_deg(7.0, 187.0) == -180.0




def test_deviating_long_lived_strong_cell_is_flagged():
    cell = run_storm()
    assert "possible_supercell" in cell.flags
    assert cell.motion_deviation_deg is not None
    assert cell.motion_deviation_deg > 25.0


def test_left_mover_is_also_flagged():
    cell = run_storm(flow_at=flow_const(15.0, 130.0))
    assert "possible_supercell" in cell.flags
    assert cell.motion_deviation_deg is not None and cell.motion_deviation_deg < -25.0




def test_young_cell_is_not_flagged():
    cell = run_storm(frames=6)
    assert "possible_supercell" not in cell.flags
    assert cell.motion_deviation_deg is None


def test_cell_moving_with_the_flow_is_not_flagged():
    cell = run_storm(flow_at=flow_const(15.0, 90.0))
    assert "possible_supercell" not in cell.flags


def test_low_lightning_rate_is_not_flagged():
    cell = run_storm(rate=2.0)
    assert "possible_supercell" not in cell.flags


def test_weak_core_is_not_flagged():
    cell = run_storm(peak=50.0)
    assert "possible_supercell" not in cell.flags


def test_calm_flow_is_not_flagged():
    cell = run_storm(flow_at=flow_const(1.0, FLOW_BEARING_RIGHT))
    assert "possible_supercell" not in cell.flags


def test_missing_environment_is_not_flagged():
    cell = run_storm(flow_at=lambda lon, lat: (None, None))
    assert "possible_supercell" not in cell.flags
    assert cell.max_dbz >= 55


def test_no_flow_callable_is_safe():
    tr = CellTracker(Settings())
    g = frame()
    blob(g, 90, 90, 58)
    out = tr.update(T0, g, TRANSFORM)
    assert out and "possible_supercell" not in out[0].flags
