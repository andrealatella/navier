"""Common ingestor interface + health model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..models import LightningStrike, UserPosition, utcnow

if TYPE_CHECKING:
    from ..store.radar import RadarFrameEntry

StrikeSink = Callable[[list[LightningStrike]], Awaitable[None]]
RadarFrameSink = Callable[["RadarFrameEntry"], Awaitable[None]]
RadarFramesSink = Callable[[list["RadarFrameEntry"]], Awaitable[None]]
PositionSink = Callable[[UserPosition], Awaitable[None]]


class HealthState(StrEnum):
    STARTING = "starting"
    OK = "ok"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    DISABLED = "disabled"


class SourceHealth(BaseModel):
    """Live status of one ingestor, surfaced to the UI status panel."""

    name: str
    state: HealthState
    detail: str = ""
    last_event_ts: datetime | None = None
    events_total: int = 0

    @property
    def age_s(self) -> float | None:
        if self.last_event_ts is None:
            return None
        return (utcnow() - self.last_event_ts).total_seconds()


class Ingestor(ABC):
    """Generic source: one supervised async `run()` plus a `health()` snapshot."""

    name: str = "base"

    def __init__(self) -> None:
        self._state = HealthState.STARTING
        self._detail = ""
        self._last_event_ts: datetime | None = None
        self._events_total = 0

    @abstractmethod
    async def run(self) -> None:
        """Long-running loop. May raise; the manager will restart it."""

    def _mark_events(self, n: int) -> None:
        """Bump the freshness counters after emitting `n` normalized events."""
        if n <= 0:
            return
        self._events_total += n
        self._last_event_ts = utcnow()

    def _set_state(self, state: HealthState, detail: str = "") -> None:
        self._state = state
        self._detail = detail

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            state=self._state,
            detail=self._detail,
            last_event_ts=self._last_event_ts,
            events_total=self._events_total,
        )


class LightningIngestor(Ingestor):
    """Ingestor that emits batches of lightning strikes through a StrikeSink."""

    def __init__(self, sink: StrikeSink) -> None:
        super().__init__()
        self._sink = sink

    async def _emit(self, strikes: list[LightningStrike]) -> None:
        if not strikes:
            return
        self._mark_events(len(strikes))
        await self._sink(strikes)
