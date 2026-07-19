"""Blitzortung lightning ingestor."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime

import websockets

from ..config import Settings
from ..models import LightningStrike
from .base import HealthState, LightningIngestor, StrikeSink

logger = logging.getLogger("navier.ingest.blitzortung")

SERVERS = (
    "wss://ws1.blitzortung.org",
    "wss://ws7.blitzortung.org",
    "wss://ws8.blitzortung.org",
)
HANDSHAKE = json.dumps({"a": 111})
RECV_TIMEOUT_S = 90.0


def decode(b: str) -> str:
    """Decompress a Blitzortung live-map message (LZW variant) to a JSON string."""
    if not b:
        return ""
    e: dict[int, str] = {}
    c = b[0]
    f = c
    out = [c]
    h = 256
    o = h
    for i in range(1, len(b)):
        code = ord(b[i])
        if h > code:
            a = b[i]
        else:
            a = e[code] if code in e else (f + c)
        out.append(a)
        c = a[0]
        e[o] = f + c
        o += 1
        f = a
    return "".join(out)


class BlitzortungIngestor(LightningIngestor):
    name = "blitzortung"

    def __init__(self, sink: StrikeSink, settings: Settings) -> None:
        super().__init__(sink)
        self._s = settings
        self._server_idx = 0

    def _in_italy(self, lat: float, lon: float) -> bool:
        s = self._s
        return s.italy_bbox_s <= lat <= s.italy_bbox_n and s.italy_bbox_w <= lon <= s.italy_bbox_e

    def _parse(self, raw: str) -> list[LightningStrike]:
        """Decode + parse one raw message into 0..1 in-bbox strikes."""
        try:
            obj = json.loads(decode(raw))
        except Exception:  # noqa: BLE001
            logger.debug("undecodable blitzortung frame (len=%d)", len(raw))
            return []
        try:
            lat = float(obj["lat"])
            lon = float(obj["lon"])
            if not self._in_italy(lat, lon):
                return []
            ts = datetime.fromtimestamp(int(obj["time"]) / 1e9, tz=UTC)
        except (KeyError, ValueError, TypeError, OSError):
            return []
        return [LightningStrike(ts=ts, lat=lat, lon=lon, src="blitzortung")]

    async def run(self) -> None:
        backoff = 1.0
        while True:
            url = SERVERS[self._server_idx % len(SERVERS)]
            try:
                async with websockets.connect(url, open_timeout=10, close_timeout=5) as ws:
                    await ws.send(HANDSHAKE)
                    self._set_state(HealthState.OK, f"connesso a {url}")
                    logger.info("blitzortung connected: %s", url)
                    backoff = 1.0
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT_S)
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "ignore")
                        await self._emit(self._parse(raw))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                self._server_idx += 1
                delay = backoff + random.uniform(0, backoff)
                logger.warning("blitzortung disconnected (%s); retry in %.1fs", e, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, 30.0)
