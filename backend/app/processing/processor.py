"""Processing orchestrator: frames + strikes + position → WorldState → alerts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ..config import Settings
from ..models import LightningStrike, UserPosition
from ..store.allerte import AllerteStore
from ..store.memory import LightningStore
from ..store.meteo import MeteoStore
from ..store.radar import RadarStore
from .geo import haversine_km
from .world import WorldState, to_wire

logger = logging.getLogger("navier.processing")

Broadcast = Callable[[str, dict], Awaitable[None]]


class Processor:
    def __init__(
        self,
        settings: Settings,
        broadcast: Broadcast,
        lightning_store: LightningStore,
        radar_store: RadarStore,
        meteo_store: MeteoStore | None = None,
        allerte_store: AllerteStore | None = None,
    ) -> None:
        self._s = settings
        self._broadcast = broadcast
        self._lightning = lightning_store
        self._radar = radar_store
        self._meteo = meteo_store
        self._allerte = allerte_store
        self._enabled = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

        self._tracker = None
        self._analyzer = None
        self._engine = None
        self._cells: list = []
        self._poh_grid = None
        self._sri_grid = None
        self._last_grid_ts: datetime | None = None
        self._last_wire: dict | None = None
        self._user: UserPosition | None = None
        self._target_cell_id: int | None = None
        self._world_listener: Callable[[WorldState, list, list], None] | None = None

    async def start(self) -> None:
        try:
            from ..alerts.engine import AlertEngine
            from .cells import CellTracker
            from .lightning import LightningAnalyzer
        except Exception as e:  # noqa: BLE001
            logger.warning("processing disabled (extra missing): %s", e)
            self._enabled = False
            return
        self._tracker = CellTracker(self._s)
        self._analyzer = LightningAnalyzer(self._s)
        self._engine = AlertEngine(self._s)
        self._enabled = True
        self._task = asyncio.create_task(self._tick_loop(), name="processing_tick")
        logger.info("processing enabled: cell tracker + alert engine")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def on_radar_grid(self, ts_ms: int, grid, transform) -> None:
        """A fresh DPC dBZ grid arrived: re-segment and re-broadcast."""
        if not self._enabled:
            return
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        async with self._lock:
            clusters = self._cluster(ts)
            user_ll = (self._user.lon, self._user.lat) if self._user else None
            self._cells = await asyncio.to_thread(
                self._tracker.update,
                ts,
                grid,
                transform,
                clusters=clusters,
                cape_at=self._cape_at,
                flow_at=self._flow_at,
                user=user_ll,
            )
            self._last_grid_ts = ts
            self._apply_poh(ts)
            await self._rebuild(ts, clusters)

    async def on_position(self, user: UserPosition) -> None:
        self._user = user
        if not self._enabled:
            return
        async with self._lock:
            await self._rebuild(datetime.now(UTC))

    def _cape_at(self, lon: float, lat: float) -> float | None:
        """Sample local CAPE from the Open-Meteo grid; None if unavailable."""
        if self._meteo is None:
            return None
        cape, _ = self._meteo.sample(lon, lat)
        return cape

    def _flow_at(self, lon: float, lat: float) -> tuple[float | None, float | None]:
        """Sample the 700-500 hPa mean flow for the supercell heuristic."""
        if self._meteo is None:
            return (None, None)
        return self._meteo.sample_flow(lon, lat)

    async def on_poh_grid(self, grid) -> None:
        """A fresh DPC POH grid arrived; enrich cells + rebroadcast."""
        self._poh_grid = grid
        if not self._enabled:
            return
        async with self._lock:
            self._apply_poh()
            await self._rebuild(datetime.now(UTC))

    async def on_sri_grid(self, grid) -> None:
        """A fresh DPC SRI grid arrived; used at rebuild for FLASH_FLOOD."""
        self._sri_grid = grid
        if not self._enabled:
            return
        async with self._lock:
            await self._rebuild(datetime.now(UTC))

    def _fresh(self, grid, now: datetime):
        """Return the grid if it's within the staleness window, else None."""
        if grid is None:
            return None
        age = now.timestamp() - grid.ts_ms / 1000.0
        return grid if age <= self._s.dpc_products_stale_s else None

    def _apply_poh(self, now: datetime | None = None) -> None:
        """Set each cell's max POH under its footprint (~cell radius) from the POH grid."""
        import math

        grid = self._fresh(self._poh_grid, now or datetime.now(UTC))
        for c in self._cells:
            if grid is None:
                c.poh = None
                continue
            radius_km = max(2.0, math.sqrt(max(c.area_km2, 1.0) / math.pi))
            c.poh = grid.max_in_radius(c.centroid[0], c.centroid[1], radius_km)

    def set_target(self, cell_id: int | None) -> None:
        self._target_cell_id = cell_id

    def set_world_listener(self, listener: Callable[[WorldState, list, list], None] | None) -> None:
        """Register an observer (the co-pilot) called with (world, active, fired) each rebuild."""
        self._world_listener = listener

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._s.processing_tick_s)
            try:
                async with self._lock:
                    await self._rebuild(datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("processing tick failed")

    def _cluster(self, now: datetime) -> list:
        return self._analyzer.analyze(self._lightning.recent(), now)

    async def _rebuild(self, now: datetime, clusters: list | None = None) -> None:
        """Fuse the current world, evaluate alerts, and broadcast."""
        from .cells import refresh_dynamic

        if clusters is None:
            clusters = self._cluster(now)
        user_ll = (self._user.lon, self._user.lat) if self._user else None
        refresh_dynamic(self._cells, clusters, user_ll)

        local_cape: float | None = None
        local_shear: float | None = None
        if self._user is not None and self._meteo is not None:
            local_cape, local_shear = self._meteo.sample(self._user.lon, self._user.lat)

        local_sri: float | None = None
        sri = self._fresh(self._sri_grid, now)
        if self._user is not None and sri is not None:
            local_sri = sri.max_in_radius(
                self._user.lon, self._user.lat, self._s.sri_sample_radius_km
            )

        dpc_level: str | None = None
        if self._user is not None and self._allerte is not None and self._allerte.available:
            dpc_level = self._allerte.level_at(self._user.lon, self._user.lat)

        ws = WorldState(
            ts=now,
            cells=list(self._cells),
            clusters=clusters,
            user=self._user,
            nearest_strike_km=self._nearest_strike_km(now),
            radar_age_s=self._radar_age_s(now),
            lightning_age_s=self._lightning_age_s(now),
            cape=local_cape,
            shear_ms=local_shear,
            local_sri_mmh=local_sri,
            dpc_alert_level=dpc_level,
            target_cell_id=self._target_cell_id,
            target_severity_drop=self._tracker.track_severity_drop(self._target_cell_id, 900.0)
            if self._target_cell_id is not None
            else None,
        )
        active, fired = self._engine.evaluate(ws, now)
        from ..alerts.engine import alert_wire

        alerts = [alert_wire(a) for a in active]
        payload = to_wire(ws, alerts)
        self._last_wire = payload
        await self._broadcast("world_state", payload)

        if self._world_listener is not None:
            try:
                self._world_listener(ws, active, fired)
            except Exception:  # noqa: BLE001
                logger.exception("world listener failed")

    def latest_world_wire(self) -> dict | None:
        """The most recent `world_state` payload, to prime a fresh client."""
        return self._last_wire

    def current_user(self) -> UserPosition | None:
        """The last known user position, used as the default route start."""
        return self._user

    def current_cells(self) -> list:
        """A snapshot of the currently tracked cells (for intercept / cone checks)."""
        return list(self._cells)

    def find_cell(self, cell_id: int):
        return next((c for c in self._cells if c.id == cell_id), None)

    def _nearest_strike_km(self, now: datetime) -> float | None:
        if self._user is None:
            return None
        window = self._s.lightning_near_window_s
        best: float | None = None
        for s in self._lightning.recent():
            if (now - s.ts).total_seconds() > window:
                continue
            d = haversine_km(self._user.lon, self._user.lat, s.lon, s.lat)
            if best is None or d < best:
                best = d
        return best

    def _radar_age_s(self, now: datetime) -> float | None:
        if self._last_grid_ts is not None:
            return (now - self._last_grid_ts).total_seconds()
        return self._radar.latest_age_s("dpc")

    def _lightning_age_s(self, now: datetime) -> float | None:
        recent: list[LightningStrike] = self._lightning.recent()
        if not recent:
            return None
        newest = max(s.ts for s in recent)
        return (now - newest).total_seconds()

    def current_alerts_wire(self) -> list[dict]:
        """Active alerts for a freshly-connected client."""
        if not self._enabled or self._engine is None:
            return []
        from ..alerts.engine import alert_wire

        return [alert_wire(a) for a in self._engine.active()]
