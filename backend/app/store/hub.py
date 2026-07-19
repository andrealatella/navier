"""WebSocket connection hub."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("navier.hub")


class ConnectionHub:
    """Tracks live WebSocket clients and fans messages out to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._recorder: Callable[[str, dict[str, Any]], None] | None = None

    def set_recorder(self, recorder: Callable[[str, dict[str, Any]], None] | None) -> None:
        """Install (or clear) a tap that records every broadcast for replay."""
        self._recorder = recorder

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("client disconnected (%d total)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def send(self, ws: WebSocket, type_: str, payload: dict[str, Any] | None = None) -> None:
        """Send one tagged message to a single client, ignoring dead sockets."""
        try:
            await ws.send_json({"type": type_, "payload": payload or {}})
        except Exception:  # noqa: BLE001
            logger.debug("send failed; dropping client")
            await self.disconnect(ws)

    async def broadcast(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        """Fan a tagged message out to every connected client (and the recorder)."""
        if self._recorder is not None:
            try:
                self._recorder(type_, payload or {})
            except Exception:  # noqa: BLE001
                logger.debug("session recorder failed on %s", type_)
        async with self._lock:
            targets = list(self._clients)
        for ws in targets:
            await self.send(ws, type_, payload)


hub = ConnectionHub()
