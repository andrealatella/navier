"""Session recorder: writes every broadcast to a replayable JSONL log."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .radar import radar_store

logger = logging.getLogger("navier.recorder")

_IGNORE = {"source_health", "recorder_status"}


class SessionRecorder:
    def __init__(self, sessions_dir: Path) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.name = f"session_{stamp}"
        self._dir = sessions_dir / self.name
        self._frames_dir = self._dir / "frames"
        self._frames_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "events.jsonl"
        self._fh = self._path.open("a", encoding="utf-8")
        self._start_ms = int(datetime.now(UTC).timestamp() * 1000)
        self._saved_frames: set[int] = set()
        self._count = 0
        self._bytes = 0
        logger.info("recording session to %s", self._path)

    @property
    def count(self) -> int:
        """Events taped so far (shown next to the REC button)."""
        return self._count

    @property
    def size_bytes(self) -> int:
        """Bytes written so far, JSONL + frame PNGs."""
        return self._bytes

    def record(self, type_: str, payload: dict) -> None:
        """Append one broadcast (sync, called from hub.broadcast). Best-effort."""
        if type_ in _IGNORE:
            return
        t = int(datetime.now(UTC).timestamp() * 1000) - self._start_ms
        line = json.dumps({"t": t, "type": type_, "payload": payload}) + "\n"
        self._fh.write(line)
        self._fh.flush()
        self._count += 1
        self._bytes += len(line.encode("utf-8"))
        if type_ == "radar_frames":
            self._save_frames(payload)

    def _save_frames(self, payload: dict) -> None:
        """Persist any new DPC image PNGs so replay can serve them from the session."""
        for f in payload.get("frames", []):
            ts = f.get("ts")
            if not isinstance(ts, int) or ts in self._saved_frames:
                continue
            png = radar_store.get_png(ts)
            if png:
                (self._frames_dir / f"{ts}.png").write_bytes(png)
                self._saved_frames.add(ts)
                self._bytes += len(png)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass
        if self._count == 0:
            try:
                shutil.rmtree(self._dir)
                logger.info("session %s discarded (nothing recorded)", self.name)
            except Exception:  # noqa: BLE001
                pass
            return
        logger.info(
            "session %s recorded (%d events, %.1f MB)", self.name, self._count, self._bytes / 1e6
        )


def list_sessions(sessions_dir: Path) -> list[dict]:
    """List recorded sessions (newest first) for `GET /api/sessions`."""
    if not sessions_dir.exists():
        return []
    out = []
    for d in sessions_dir.iterdir():
        events = d / "events.jsonl"
        if not events.is_file():
            continue
        st = events.stat()
        frames = d / "frames"
        n_frames = sum(1 for _ in frames.glob("*.png")) if frames.is_dir() else 0
        out.append(
            {
                "name": d.name,
                "size_bytes": st.st_size,
                "modified_ms": int(st.st_mtime * 1000),
                "frames": n_frames,
            }
        )
    out.sort(key=lambda s: s["modified_ms"], reverse=True)
    return out
