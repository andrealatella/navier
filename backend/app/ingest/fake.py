"""Synthetic lightning generator for development."""

from __future__ import annotations

import asyncio
import math
import random

from ..models import LightningStrike, utcnow
from .base import HealthState, LightningIngestor, StrikeSink


class _Cell:
    def __init__(self) -> None:
        self.lat = random.uniform(38.0, 46.0)
        self.lon = random.uniform(7.5, 17.0)
        heading = random.uniform(0, 2 * math.pi)
        speed = random.uniform(0.002, 0.006)
        self.dlat = speed * math.cos(heading)
        self.dlon = speed * math.sin(heading)
        self.intensity = random.uniform(0.3, 1.0)

    def step(self) -> None:
        self.lat += self.dlat
        self.lon += self.dlon
        self.intensity = max(0.05, min(1.0, self.intensity + random.uniform(-0.1, 0.1)))
        if not (36.0 <= self.lat <= 47.5 and 6.0 <= self.lon <= 19.0):
            self.__init__()


class FakeLightningIngestor(LightningIngestor):
    name = "fake_lightning"

    def __init__(self, sink: StrikeSink, n_cells: int = 3, tick_s: float = 0.5) -> None:
        super().__init__(sink)
        self._n_cells = n_cells
        self._tick_s = tick_s

    async def run(self) -> None:
        cells = [_Cell() for _ in range(self._n_cells)]
        self._set_state(HealthState.OK, "generatore sintetico")
        while True:
            await asyncio.sleep(self._tick_s)
            strikes: list[LightningStrike] = []
            for cell in cells:
                cell.step()
                for _ in range(random.randint(0, round(5 * cell.intensity))):
                    strikes.append(
                        LightningStrike(
                            ts=utcnow(),
                            lat=cell.lat + random.gauss(0, 0.06),
                            lon=cell.lon + random.gauss(0, 0.06),
                            src="fake",
                        )
                    )
            await self._emit(strikes)
