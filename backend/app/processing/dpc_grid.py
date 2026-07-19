"""Decode + point-sample an auxiliary DPC product grid (POH, SRI)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile

NODATA_BELOW = -100.0


@dataclass
class ProductGrid:
    """One decoded DPC product frame: native values + geo-referencing, sampled by point."""

    values: np.ndarray
    transform: Affine
    to_native: Transformer
    ts_ms: int
    px_m: float

    def _rc(self, lon: float, lat: float) -> tuple[int, int]:
        x, y = self.to_native.transform(lon, lat)
        col, row = ~self.transform * (x, y)
        return int(row), int(col)

    def sample(self, lon: float, lat: float) -> float | None:
        """Value at (lon, lat), or None if off-grid / nodata."""
        h, w = self.values.shape
        row, col = self._rc(lon, lat)
        if 0 <= row < h and 0 <= col < w:
            v = self.values[row, col]
            return None if math.isnan(v) else float(v)
        return None

    def max_in_radius(self, lon: float, lat: float, radius_km: float) -> float | None:
        """Max value within `radius_km` of (lon, lat) - 'max under the footprint'."""
        h, w = self.values.shape
        row, col = self._rc(lon, lat)
        rad_px = max(1, int(math.ceil(radius_km * 1000.0 / self.px_m)))
        r0, r1 = max(0, row - rad_px), min(h, row + rad_px + 1)
        c0, c1 = max(0, col - rad_px), min(w, col + rad_px + 1)
        if r0 >= r1 or c0 >= c1:
            return None
        window = self.values[r0:r1, c0:c1]
        finite = window[np.isfinite(window)]
        return float(finite.max()) if finite.size else None


def decode_product(tif_bytes: bytes, ts_ms: int) -> ProductGrid:
    """Decode a POH/SRI GeoTIFF into a point-samplable native grid."""
    with MemoryFile(tif_bytes) as mem, mem.open() as src:
        band = src.read(1).astype(np.float32)
        band[band <= NODATA_BELOW] = np.nan
        transform = src.transform
        to_native = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        px_m = abs(transform.a)
    return ProductGrid(
        values=band, transform=transform, to_native=to_native, ts_ms=ts_ms, px_m=px_m
    )
