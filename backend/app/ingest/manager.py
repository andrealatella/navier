"""Ingestor supervisor."""

from __future__ import annotations

import asyncio
import logging
import random

from .base import HealthState, Ingestor, SourceHealth

logger = logging.getLogger("navier.ingest.manager")


class IngestorManager:
    def __init__(self) -> None:
        self._ingestors: list[Ingestor] = []
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    def register(self, ingestor: Ingestor) -> None:
        self._ingestors.append(ingestor)

    async def start(self) -> None:
        self._stopping = False
        for ing in self._ingestors:
            task = asyncio.create_task(self._supervise(ing), name=f"ingest:{ing.name}")
            self._tasks.append(task)
        names = [i.name for i in self._ingestors]
        logger.info("started %d ingestor(s): %s", len(self._tasks), names)

    async def _supervise(self, ing: Ingestor) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                await ing.run()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("ingestor %s crashed; restarting in %.1fs", ing.name, backoff)
                ing._set_state(HealthState.DEGRADED, "riavvio dopo errore")
                await asyncio.sleep(backoff + random.uniform(0, backoff))
                backoff = min(backoff * 2, 30.0)
            else:
                await asyncio.sleep(1.0)

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for ing in self._ingestors:
            ing._set_state(HealthState.STOPPED, "")
        self._tasks.clear()
        logger.info("all ingestors stopped")

    def health(self) -> list[SourceHealth]:
        return [ing.health() for ing in self._ingestors]
