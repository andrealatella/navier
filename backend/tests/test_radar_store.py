"""RadarStore tests: ring management, wire form, and the DPC→RainViewer fallback."""

from __future__ import annotations

import time

from app.store.radar import RadarFrameEntry, RadarStore

NOW_MS = int(time.time() * 1000)
MIN = 60_000


def _img(ts_ms: int) -> RadarFrameEntry:
    return RadarFrameEntry(
        ts_ms=ts_ms, source="dpc", kind="image", png=b"x", bounds=[4.5, 35.0, 20.5, 48.0]
    )


def _tile(ts_ms: int) -> RadarFrameEntry:
    return RadarFrameEntry(
        ts_ms=ts_ms, source="rainviewer", kind="tiles", tile_url=f"http://t/{ts_ms}/{{z}}.png"
    )


def test_add_frame_sorts_and_caps():
    s = RadarStore(history=3, stale_s=1200)
    for ts in (NOW_MS, NOW_MS - 2 * MIN, NOW_MS - MIN, NOW_MS - 3 * MIN):
        s.add_frame(_img(ts))
    ring = s._rings["dpc"]
    assert [f.ts_ms for f in ring] == [NOW_MS - 2 * MIN, NOW_MS - MIN, NOW_MS]
    assert s.frame_count("dpc") == 3


def test_add_frame_dedups_same_ts():
    s = RadarStore(history=10, stale_s=1200)
    s.add_frame(_img(NOW_MS))
    s.add_frame(_img(NOW_MS))
    assert s.frame_count("dpc") == 1


def test_get_png_by_ts():
    s = RadarStore(history=10, stale_s=1200)
    s.add_frame(_img(NOW_MS))
    assert s.get_png(NOW_MS) == b"x"
    assert s.get_png(NOW_MS + 999) is None


def test_active_source_prefers_fresh_dpc():
    s = RadarStore(history=10, stale_s=1200)
    s.add_frame(_img(NOW_MS - MIN))
    s.replace("rainviewer", [_tile(NOW_MS)])
    assert s.active_source() == "dpc"


def test_active_source_falls_back_when_dpc_stale():
    s = RadarStore(history=10, stale_s=600)
    s.add_frame(_img(NOW_MS - 30 * MIN))
    s.replace("rainviewer", [_tile(NOW_MS)])
    assert s.active_source() == "rainviewer"


def test_active_source_rainviewer_only():
    s = RadarStore(history=10, stale_s=1200)
    s.replace("rainviewer", [_tile(NOW_MS)])
    assert s.active_source() == "rainviewer"


def test_active_source_none_when_empty():
    s = RadarStore(history=10, stale_s=1200)
    assert s.active_source() is None
    assert s.active_payload()["frames"] == []


def test_wire_form_image_vs_tiles():
    img = _img(NOW_MS).wire()
    assert img["url"] == f"/api/radar/frame/{NOW_MS}.png"
    assert img["bounds"] == [4.5, 35.0, 20.5, 48.0]
    tile = _tile(NOW_MS).wire()
    assert "{z}" in tile["tile_url"]
    assert "url" not in tile


def test_active_payload_reports_source_and_attribution():
    s = RadarStore(history=10, stale_s=1200)
    s.add_frame(_img(NOW_MS))
    payload = s.active_payload()
    assert payload["source"] == "dpc"
    assert payload["kind"] == "image"
    assert "Protezione Civile" in payload["attribution"]
    assert len(payload["frames"]) == 1
