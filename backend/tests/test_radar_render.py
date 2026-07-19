"""Render pipeline test."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rasterio", reason="processing extra not installed")

from app.processing.radar_render import render_vmi  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "dpc_vmi_sample.tif"

PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")


@pytest.fixture(scope="module")
def rendered():
    if not FIXTURE.exists():
        pytest.skip("VMI fixture not present")
    return render_vmi(FIXTURE.read_bytes())


def test_output_is_png(rendered):
    assert rendered.png[:8] == PNG_MAGIC
    assert len(rendered.png) > 1000


def test_bounds_cover_italy(rendered):
    w, s, e, n = rendered.bounds
    assert 4.0 < w < 6.0
    assert 19.5 < e < 21.5
    assert 34.5 < s < 36.0
    assert 47.0 < n < 48.5
    assert w < e and s < n


def test_dbz_in_physical_range(rendered):
    assert 0.0 <= rendered.max_dbz <= 80.0


def test_dimensions_positive(rendered):
    assert rendered.width > 0 and rendered.height > 0
