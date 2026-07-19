"""In-memory radar frame store with automatic DPC to RainViewer fallback."""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..config import settings

ATTRIBUTION: dict[str, str] = {
    "dpc": "Radar-DPC, Dipartimento della Protezione Civile",
    "rainviewer": "RainViewer",
}


@dataclass
class RadarFrameEntry:
    """One radar mosaic frame. `image` frames carry PNG bytes + lon/lat bounds"""

    ts_ms: int
    source: str
    kind: str
    png: bytes | None = None
    bounds: list[float] | None = None
    max_dbz: float | None = None
    tile_url: str | None = None

    def wire(self) -> dict:
        """Compact form for the WS/REST payload (small payloads)."""
        if self.kind == "image":
            return {
                "ts": self.ts_ms,
                "url": f"/api/radar/frame/{self.ts_ms}.png",
                "bounds": self.bounds,
                "max_dbz": self.max_dbz,
            }
        return {"ts": self.ts_ms, "tile_url": self.tile_url}


class RadarStore:
    def __init__(self, history: int, stale_s: float) -> None:
        self._history = history
        self._stale_ms = int(stale_s * 1000)
        self._rings: dict[str, list[RadarFrameEntry]] = {"dpc": [], "rainviewer": []}

    def add_frame(self, entry: RadarFrameEntry) -> None:
        """Insert/replace one frame (DPC), keeping the ring time-sorted and capped."""
        ring = self._rings[entry.source]
        ring[:] = [f for f in ring if f.ts_ms != entry.ts_ms]
        ring.append(entry)
        ring.sort(key=lambda f: f.ts_ms)
        if len(ring) > self._history:
            del ring[: -self._history]

    def replace(self, source: str, entries: list[RadarFrameEntry]) -> None:
        """Replace a whole source's ring at once (RainViewer sends full lists)."""
        entries = sorted(entries, key=lambda f: f.ts_ms)[-self._history :]
        self._rings[source] = entries

    def has(self, source: str, ts_ms: int) -> bool:
        return any(f.ts_ms == ts_ms for f in self._rings[source])

    def get_png(self, ts_ms: int) -> bytes | None:
        for f in self._rings["dpc"]:
            if f.ts_ms == ts_ms and f.png is not None:
                return f.png
        return None

    def frame_count(self, source: str) -> int:
        return len(self._rings[source])

    def latest_age_s(self, source: str) -> float | None:
        ring = self._rings[source]
        if not ring:
            return None
        return (int(time.time() * 1000) - ring[-1].ts_ms) / 1000.0

    def active_source(self) -> str | None:
        """Which source the map should show: DPC if fresh, else RainViewer."""
        now_ms = int(time.time() * 1000)
        dpc = self._rings["dpc"]
        if dpc and (now_ms - dpc[-1].ts_ms) <= self._stale_ms:
            return "dpc"
        if self._rings["rainviewer"]:
            return "rainviewer"
        if dpc:
            return "dpc"
        return None

    def active_payload(self) -> dict:
        """The `radar_frames` message body: the active source's ordered frames."""
        src = self.active_source()
        if src is None:
            return {"source": None, "kind": None, "attribution": "", "frames": []}
        ring = self._rings[src]
        return {
            "source": src,
            "kind": ring[0].kind if ring else None,
            "attribution": ATTRIBUTION.get(src, ""),
            "frames": [f.wire() for f in ring],
        }


radar_store = RadarStore(
    history=settings.radar_history_frames,
    stale_s=settings.radar_stale_s,
)
