"""DPC radar ingestor for the national VMI mosaic."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from ..config import Settings
from ..store.radar import RadarFrameEntry, RadarStore
from .base import HealthState, Ingestor, RadarFrameSink

logger = logging.getLogger("navier.ingest.dpc_radar")

SLOT_MS = 300_000
BACKFILL_CONCURRENCY = 6
TRACK_FRAMES = 4

GridSink = Callable[[int, object, object], Awaitable[None]]
FetchResult = tuple[RadarFrameEntry, object, object]


def _key_to_ts_ms(key: str) -> int | None:
    """Parse the S3 key (e.g. `VMI/12-07-2026-19-35.tif`) to the frame's epoch ms."""
    try:
        name = key.rsplit("/", 1)[-1].removesuffix(".tif")
        dt = datetime.strptime(name, "%d-%m-%Y-%H-%M").replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except (ValueError, IndexError):
        return None


class DpcRadarIngestor(Ingestor):
    name = "dpc_radar"

    def __init__(
        self,
        sink: RadarFrameSink,
        settings: Settings,
        store: RadarStore,
        grid_sink: GridSink | None = None,
    ) -> None:
        super().__init__()
        self._sink = sink
        self._grid_sink = grid_sink
        self._s = settings
        self._store = store
        self._processed_keys: set[str] = set()
        self._render = None

    async def run(self) -> None:
        try:
            from ..processing.radar_render import render_vmi
        except Exception as e:  # noqa: BLE001
            self._set_state(
                HealthState.DEGRADED,
                "modulo processing assente: 'pip install -e \".[processing]\"'",
            )
            logger.warning("dpc_radar disabled: %s (RainViewer covers the map)", e)
            await asyncio.Event().wait()
            return
        self._render = render_vmi

        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            await self._backfill(client)
            while True:
                try:
                    latest = await self._latest_ts(client)
                    if latest and not self._store.has("dpc", latest):
                        result = await self._fetch_frame(client, latest)
                        if result:
                            entry, grid, transform = result
                            await self._sink(entry)
                            await self._push_grid(entry.ts_ms, grid, transform)
                    n = self._store.frame_count("dpc")
                    self._set_state(HealthState.OK, f"{n} frame · {self._s.radar_product}")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                    logger.warning("dpc_radar poll error: %s", e)
                await asyncio.sleep(self._s.radar_poll_s)

    async def _latest_ts(self, client: httpx.AsyncClient) -> int | None:
        r = await client.get(
            f"{self._s.dpc_api_base}/findLastProductByType",
            params={"type": self._s.radar_product},
        )
        r.raise_for_status()
        products = r.json().get("lastProducts") or []
        return int(products[0]["time"]) if products else None

    async def _fetch_frame(self, client: httpx.AsyncClient, ts_ms: int) -> FetchResult | None:
        """Download + render one product slot into an image frame + its dBZ grid (or None)."""
        r = await client.post(
            f"{self._s.dpc_api_base}/downloadProduct",
            json={"productType": self._s.radar_product, "productDate": ts_ms},
        )
        r.raise_for_status()
        info = r.json()
        url, key = info.get("url"), info.get("key", "")
        if not url or key in self._processed_keys:
            return None
        actual_ts = _key_to_ts_ms(key) or ts_ms
        if self._store.has("dpc", actual_ts):
            self._processed_keys.add(key)
            return None

        self._processed_keys.add(key)
        try:
            tif = (await client.get(url)).content
            rendered = await asyncio.to_thread(self._render, tif)
        except BaseException:
            self._processed_keys.discard(key)
            raise
        self._mark_events(1)
        entry = RadarFrameEntry(
            ts_ms=actual_ts,
            source="dpc",
            kind="image",
            png=rendered.png,
            bounds=rendered.bounds,
            max_dbz=rendered.max_dbz,
        )
        return entry, rendered.grid, rendered.transform

    async def _push_grid(self, ts_ms: int, grid, transform) -> None:
        """Hand one decoded dBZ grid to the cell tracker (frames must arrive in time order)."""
        if self._grid_sink is None or grid is None:
            return
        try:
            await self._grid_sink(ts_ms, grid, transform)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("cell tracker rejected frame %d: %s", ts_ms, e)

    async def _backfill(self, client: httpx.AsyncClient) -> None:
        """Fetch the last ~90 min so the slider is populated on startup."""
        try:
            latest = await self._latest_ts(client)
        except Exception as e:  # noqa: BLE001
            logger.warning("dpc_radar backfill skipped (no latest ts): %s", e)
            return
        if not latest:
            return

        grids: dict[int, tuple] = {}
        track_from = latest - (TRACK_FRAMES - 1) * SLOT_MS
        await self._backfill_slot(client, latest, grids, track_from)
        n = self._store.frame_count("dpc")
        if n:
            self._set_state(HealthState.OK, f"{n} frame · {self._s.radar_product}")

        sem = asyncio.Semaphore(BACKFILL_CONCURRENCY)

        async def guarded(ts: int) -> None:
            async with sem:
                await self._backfill_slot(client, ts, grids, track_from)

        older = [latest - k * SLOT_MS for k in range(1, self._s.radar_history_frames)]
        await asyncio.gather(*(guarded(ts) for ts in older))

        for ts in sorted(grids):
            await self._push_grid(ts, *grids.pop(ts))
        logger.info("dpc_radar backfilled %d frame(s)", self._store.frame_count("dpc"))

    async def _backfill_slot(
        self, client: httpx.AsyncClient, ts: int, grids: dict[int, tuple], track_from: int
    ) -> None:
        """Fetch one backfill slot: publish the image now, keep its grid for the ordered replay."""
        try:
            result = await self._fetch_frame(client, ts)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.debug("dpc_radar backfill slot %d failed: %s", ts, e)
            return
        if result is None:
            return
        entry, grid, transform = result
        if entry.ts_ms >= track_from:
            grids[entry.ts_ms] = (grid, transform)
        await self._sink(entry)
