"""DPC product grid (POH/SRI) decode + sampling tests."""

from __future__ import annotations

import numpy as np
from affine import Affine
from rasterio.io import MemoryFile

from app.processing.dpc_grid import decode_product


def _make_tif(values: np.ndarray) -> bytes:
    """A 1°/pixel GeoTIFF in EPSG:4326 with top-left at lon=0, lat=5 (5×5)."""
    transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 5.0)
    h, w = values.shape
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            height=h,
            width=w,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(values.astype(np.float32), 1)
        return mem.read()


def test_decode_nodata_to_nan_and_sample():
    vals = np.zeros((5, 5), dtype=np.float32)
    vals[2, 2] = 42.0
    vals[0, 0] = -9999.0
    pg = decode_product(_make_tif(vals), ts_ms=1234)
    assert pg.ts_ms == 1234
    assert pg.sample(2.5, 2.5) == 42.0
    assert pg.sample(0.5, 4.5) is None
    assert pg.sample(3.5, 2.5) == 0.0


def test_sample_off_grid_returns_none():
    pg = decode_product(_make_tif(np.zeros((5, 5), np.float32)), ts_ms=0)
    assert pg.sample(99.0, 99.0) is None


def _make_tif_metric(values: np.ndarray) -> bytes:
    """An 11×11 GeoTIFF in EPSG:3857 with 1 km pixels centred on (0, 0) so px_m=1000."""
    n = 5
    transform = Affine(1000.0, 0.0, -(n + 0.5) * 1000.0, 0.0, -1000.0, (n + 0.5) * 1000.0)
    h, w = values.shape
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff", height=h, width=w, count=1, dtype="float32",
            crs="EPSG:3857", transform=transform,
        ) as dst:
            dst.write(values.astype(np.float32), 1)
        return mem.read()


def test_max_in_radius_window():
    vals = np.zeros((11, 11), dtype=np.float32)
    vals[5, 8] = 80.0
    pg = decode_product(_make_tif_metric(vals), ts_ms=0)
    assert pg.px_m == 1000.0
    assert pg.sample(0.0, 0.0) == 0.0
    assert pg.max_in_radius(0.0, 0.0, radius_km=2.0) == 0.0
    assert pg.max_in_radius(0.0, 0.0, radius_km=4.0) == 80.0
