"""Backend voice pipeline: one synth and one player behind a priority queue."""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..models import Alert
from .player import Player
from .system import SystemSynth

logger = logging.getLogger("navier.tts")

_PRIO_P1 = 0
_PRIO_VOICE = 1
_PRIO_PROACTIVE = 2
_PRIO_BY_ALERT = {1: _PRIO_P1, 2: _PRIO_VOICE, 3: _PRIO_VOICE}

STATIC_PHRASES = (
    "Fulmini nelle vicinanze. Resta in auto.",
    "Rischio nubifragio. Evita sottopassi e strade allagate.",
)


@dataclass
class _Item:
    text: str | None
    wav: Path | None
    label: str


class TtsService:
    def __init__(
        self,
        settings: Settings,
        synth: SystemSynth | None = None,
        player: Player | None = None,
    ) -> None:
        self._s = settings
        self._synth = synth if synth is not None else SystemSynth(settings)
        self._player = player if player is not None else Player(settings)
        self._enabled = settings.enable_tts
        self._available = False
        self._speaking = False
        self._queue: asyncio.PriorityQueue | None = None
        self._seq = itertools.count()
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._s.enable_tts:
            logger.info("tts disabled (ENABLE_TTS=0)")
            return
        if not self._synth.available():
            logger.warning("tts dormant: no system TTS (powershell not found)")
            return
        if not self._player.available():
            logger.warning("tts dormant: no audio output (install the `voice` extra)")
            return
        self._queue = asyncio.PriorityQueue()
        self._available = True
        self._worker_task = asyncio.create_task(self._worker(), name="tts_worker")
        await asyncio.to_thread(self._warm)
        logger.info("tts enabled: Windows system voice")

    def _warm(self) -> None:
        self._synth.register_persistent(STATIC_PHRASES)
        self._synth.prune()
        for text in STATIC_PHRASES:
            self._synth.synth(text)

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._worker_task = None
        self._player.stop()

    def speak_alerts(self, fired: list[Alert]) -> None:
        """Voice newly-fired deterministic alerts; a P1 interrupts everything."""
        for a in fired:
            prio = _PRIO_BY_ALERT.get(a.priority, _PRIO_VOICE)
            self.say(a.tts_text, priority=prio, interrupt=(a.priority == 1), label=a.rule_id)

    def speak_copilot(self, text: str, kind: str) -> None:
        """Voice a co-pilot line. Never interrupts a safety alert."""
        prio = _PRIO_PROACTIVE if kind == "proactive" else _PRIO_VOICE
        self.say(text, priority=prio, interrupt=False, label=f"copilot:{kind}")

    def say(
        self, text: str, *, priority: int = _PRIO_VOICE, interrupt: bool = False, label: str = ""
    ) -> None:
        """Enqueue a line to speak. `interrupt` cuts the current line and clears the queue."""
        if not self._available or not self._enabled or self._queue is None:
            return
        if not (text or "").strip():
            return
        if interrupt:
            self._clear_queue()
            self._player.stop()
        self._queue.put_nowait((priority, next(self._seq), _Item(text=text, wav=None, label=label)))

    def say_wav(self, wav: Path | str, *, priority: int = _PRIO_VOICE, label: str = "wav") -> None:
        """Enqueue a ready WAV, skipping synthesis."""
        if not self._available or not self._enabled or self._queue is None:
            return
        path = Path(wav)
        if not path.exists():
            logger.warning("tts say_wav: missing file %s", path)
            return
        self._queue.put_nowait((priority, next(self._seq), _Item(text=None, wav=path, label=label)))

    def set_enabled(self, on: bool) -> None:
        """Mute/unmute from the UI. Muting stops the current line and drains the queue."""
        self._enabled = on
        if not on and self._queue is not None:
            self._clear_queue()
            self._player.stop()
        logger.info("tts %s", "on" if on else "muted")

    @property
    def available(self) -> bool:
        return self._available

    def is_speaking(self) -> bool:
        """True while a clip is actually playing."""
        return self._speaking

    def _clear_queue(self) -> None:
        assert self._queue is not None
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            _prio, _seq, item = await self._queue.get()
            try:
                if not self._enabled:
                    continue
                path: Path | None = item.wav
                if path is None and item.text:
                    path = await asyncio.to_thread(self._synth.synth, item.text)
                if path is not None:
                    self._speaking = True
                    try:
                        await asyncio.to_thread(self._player.play, path)
                    finally:
                        self._speaking = False
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("tts playback failed (%s)", item.label)
            finally:
                self._queue.task_done()
