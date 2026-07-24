"""Session replayer: re-broadcasts a recorded session."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger("navier.replayer")

Broadcast = Callable[[str, dict], Awaitable[None]]


def resolve_session(replay_file: str) -> tuple[Path, Path]:
    """Resolve REPLAY_FILE (a session dir or an events.jsonl) to (events, frames_dir)."""
    p = Path(replay_file)
    if p.is_dir():
        return (p / "events.jsonl", p / "frames")
    return (p, p.parent / "frames")


class SessionReplayer:
    def __init__(self, replay_file: str, broadcast: Broadcast, speed: float = 1.0) -> None:
        self._events_path, self._frames_dir = resolve_session(replay_file)
        self._broadcast = broadcast
        self._speed = max(0.05, speed)
        self._events: list[tuple[int, str, dict]] = []
        self._task: asyncio.Task | None = None

    def load(self) -> int:
        """Parse the JSONL into (t_ms, type, payload); return the event count."""
        events: list[tuple[int, str, dict]] = []
        with self._events_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    events.append((int(ev["t"]), str(ev["type"]), ev.get("payload") or {}))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        events.sort(key=lambda e: e[0])
        self._events = events
        return len(events)

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    @property
    def playing(self) -> bool:
        return self._task is not None

    def frame_png(self, ts_ms: int) -> bytes | None:
        """Serve a recorded radar frame by timestamp (replay fallback for the endpoint)."""
        f = self._frames_dir / f"{ts_ms}.png"
        return f.read_bytes() if f.is_file() else None

    async def start(self) -> None:
        if not self._events_path.is_file():
            logger.warning("replay: session file not found: %s", self._events_path)
            return
        n = self.load()
        if n == 0:
            logger.warning("replay: no events in %s", self._events_path)
            return
        logger.info("replay: %d events from %s at %.2fx", n, self._events_path, self._speed)
        self._task = asyncio.create_task(self._run(), name="replayer")

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            base = loop.time()
            for t_ms, type_, payload in self._events:
                target = base + (t_ms / 1000.0) / self._speed
                dt = target - loop.time()
                if dt > 0:
                    await asyncio.sleep(dt)
                try:
                    await self._broadcast(type_, payload)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.debug("replay broadcast failed on %s", type_)
            await asyncio.sleep(1.0)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
