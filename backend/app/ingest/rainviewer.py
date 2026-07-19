"""RainViewer fallback radar ingestor."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import Settings
from ..store.radar import RadarFrameEntry
from .base import HealthState, Ingestor, RadarFramesSink

logger = logging.getLogger("navier.ingest.rainviewer")


class RainViewerIngestor(Ingestor):
    name = "rainviewer"

    def __init__(self, sink: RadarFramesSink, settings: Settings) -> None:
        super().__init__()
        self._sink = sink
        self._s = settings

    def _tile_template(self, host: str, path: str) -> str:
        opts = f"{self._s.rainviewer_smooth}_{self._s.rainviewer_snow}"
        return f"{host}{path}/256/{{z}}/{{x}}/{{y}}/{self._s.rainviewer_color_scheme}/{opts}.png"

    async def run(self) -> None:
        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            while True:
                try:
                    r = await client.get(self._s.rainviewer_maps_url)
                    r.raise_for_status()
                    data = r.json()
                    host = data.get("host", "")
                    past = data.get("radar", {}).get("past", [])
                    recent = past[-self._s.radar_history_frames :]
                    frames = [
                        RadarFrameEntry(
                            ts_ms=int(p["time"]) * 1000,
                            source="rainviewer",
                            kind="tiles",
                            tile_url=self._tile_template(host, p["path"]),
                        )
                        for p in recent
                        if p.get("path")
                    ]
                    if frames:
                        self._mark_events(1)
                        await self._sink(frames)
                        self._set_state(HealthState.OK, f"{len(frames)} frame")
                    else:
                        self._set_state(HealthState.DEGRADED, "nessun frame nel JSON")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                    logger.warning("rainviewer poll error: %s", e)
                await asyncio.sleep(self._s.rainviewer_poll_s)
