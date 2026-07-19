"""Render a DPC radar GeoTIFF into a web-ready PNG overlay."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import rasterio
from PIL import Image, ImageFilter
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

if TYPE_CHECKING:
    from affine import Affine

NODATA_BELOW = -100.0
MIN_DBZ = 10.0
WEB_MERCATOR = "EPSG:3857"
WGS84 = "EPSG:4326"

BLUR_SIGMA = 1.1
EDGE_DBZ = 4.0
ALPHA_FULL_DBZ = 45.0
ALPHA_GAMMA = 0.85
MAX_ALPHA = 235

_DBZ_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (10.0, (0, 160, 220)),
    (20.0, (0, 200, 90)),
    (30.0, (240, 220, 40)),
    (40.0, (245, 150, 30)),
    (47.0, (230, 40, 40)),
    (52.0, (170, 0, 60)),
    (57.0, (220, 60, 220)),
    (65.0, (255, 255, 255)),
]


@dataclass(frozen=True)
class RenderedFrame:
    """Result of rendering one GeoTIFF: a PNG plus its lon/lat bounds."""

    png: bytes
    bounds: list[float]
    width: int
    height: int
    max_dbz: float
    grid: np.ndarray | None = None
    transform: Affine | None = None


def _dbz_colormap() -> np.ndarray:
    """Build a 256-row RGB lookup table indexed by clamped dBZ (0..64 -> 0..255)."""
    xs = np.array([s[0] for s in _DBZ_STOPS])
    r = np.array([s[1][0] for s in _DBZ_STOPS], dtype=float)
    g = np.array([s[1][1] for s in _DBZ_STOPS], dtype=float)
    b = np.array([s[1][2] for s in _DBZ_STOPS], dtype=float)
    axis = np.linspace(0.0, 64.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    lut[:, 0] = np.interp(axis, xs, r).round().astype(np.uint8)
    lut[:, 1] = np.interp(axis, xs, g).round().astype(np.uint8)
    lut[:, 2] = np.interp(axis, xs, b).round().astype(np.uint8)
    return lut


_LUT = _dbz_colormap()


def _smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian-blur a dBZ field (no-echo already set to 0) for a soft-blob look."""
    if sigma <= 0:
        return field
    u8 = np.clip(field / 64.0 * 255.0, 0, 255).astype(np.uint8)
    blurred = Image.fromarray(u8, "L").filter(ImageFilter.GaussianBlur(radius=sigma))
    return np.asarray(blurred, dtype=np.float32) / 255.0 * 64.0


def _colorize(dbz: np.ndarray) -> np.ndarray:
    """Map a (smoothed) dBZ field to an RGBA uint8 image with soft-faded edges."""
    idx = np.clip(dbz / 64.0 * 255.0, 0, 255).astype(np.uint8)
    rgb = _LUT[idx]
    a = np.clip((dbz - EDGE_DBZ) / (ALPHA_FULL_DBZ - EDGE_DBZ), 0.0, 1.0) ** ALPHA_GAMMA
    alpha = (a * MAX_ALPHA).astype(np.uint8)
    return np.dstack([rgb, alpha])


def render_vmi(tif_bytes: bytes) -> RenderedFrame:
    """Reproject a VMI GeoTIFF to Web Mercator and encode a coloured PNG overlay."""
    with MemoryFile(tif_bytes) as mem, mem.open() as src:
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src.crs, WEB_MERCATOR, src.width, src.height, *src.bounds
        )
        dbz = np.full((dst_h, dst_w), np.float32(NODATA_BELOW - 1), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dbz,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=WEB_MERCATOR,
            src_nodata=NODATA_BELOW,
            dst_nodata=NODATA_BELOW - 1,
            resampling=Resampling.nearest,
        )
        left = dst_transform.c
        top = dst_transform.f
        right = left + dst_w * dst_transform.a
        bottom = top + dst_h * dst_transform.e
        w, s, e, n = transform_bounds(WEB_MERCATOR, WGS84, left, bottom, right, top)

    valid = dbz >= MIN_DBZ
    max_dbz = float(dbz[valid].max()) if valid.any() else 0.0
    echo = np.where(valid, dbz, 0.0).astype(np.float32)
    rgba = _colorize(_smooth(echo, BLUR_SIGMA))
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return RenderedFrame(
        png=buf.getvalue(),
        bounds=[float(w), float(s), float(e), float(n)],
        width=int(dst_w),
        height=int(dst_h),
        max_dbz=max_dbz,
        grid=echo,
        transform=dst_transform,
    )
