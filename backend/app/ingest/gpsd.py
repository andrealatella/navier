"""gpsd ingestor for an optional USB GPS dongle."""

from __future__ import annotations

import asyncio
import json
import logging

from ..models import UserPosition
from .base import HealthState, Ingestor, PositionSink

logger = logging.getLogger("navier.ingest.gpsd")

_WATCH = b'?WATCH={"enable":true,"json":true}\n'


def parse_tpv(obj: dict) -> UserPosition | None:
    """A gpsd TPV object → UserPosition, or None if there's no usable 2D/3D fix."""
    if obj.get("class") != "TPV":
        return None
    if int(obj.get("mode", 0)) < 2:
        return None
    lat, lon = obj.get("lat"), obj.get("lon")
    if lat is None or lon is None:
        return None
    speed_ms = obj.get("speed")
    track = obj.get("track")
    return UserPosition(
        lat=float(lat),
        lon=float(lon),
        speed_kmh=round(float(speed_ms) * 3.6, 1) if speed_ms is not None else None,
        heading_deg=round(float(track), 1) if track is not None else None,
        source="gpsd",
    )


class GpsdIngestor(Ingestor):
    """Reads TPV fixes from a gpsd socket and pushes them as UserPosition."""

    name = "gpsd"

    def __init__(self, sink: PositionSink, host: str, port: int) -> None:
        super().__init__()
        self._sink = sink
        self._host = host
        self._port = port

    async def run(self) -> None:
        self._set_state(HealthState.STARTING, f"connessione a gpsd {self._host}:{self._port}")
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
        except OSError as e:
            self._set_state(HealthState.DEGRADED, f"gpsd irraggiungibile: {e}")
            raise
        try:
            writer.write(_WATCH)
            await writer.drain()
            self._set_state(HealthState.OK, "in attesa del fix GPS")
            while True:
                line = await reader.readline()
                if not line:
                    self._set_state(HealthState.DEGRADED, "gpsd ha chiuso la connessione")
                    raise ConnectionError("gpsd closed the stream")
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pos = parse_tpv(obj)
                if pos is None:
                    continue
                self._mark_events(1)
                self._set_state(HealthState.OK, "fix GPS attivo")
                await self._sink(pos)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
