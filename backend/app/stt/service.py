"""Push-to-talk capture feeding the storm co-pilot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..config import Settings
from ..tts.service import TtsService
from .stt import listen_and_transcribe, make_recognizer

logger = logging.getLogger("navier.stt")


def _deps_available() -> tuple[bool, str]:
    """(ok, reason): are the speech-recognition and audio deps importable?"""
    try:
        import sounddevice  # noqa: F401, PLC0415
        import speech_recognition  # noqa: F401, PLC0415
    except Exception as e:  # noqa: BLE001
        return False, f"extra 'voice' non installato ({e.__class__.__name__})"
    return True, ""


def _has_input_device() -> bool:
    """True if a default input (mic) exists, checked before opening the stream."""
    try:
        import sounddevice as sd  # noqa: PLC0415

        sd.query_devices(kind="input")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("stt: no input device: %s", e)
        return False


def _beep(settings: Settings) -> None:
    """Short tone so the operator knows capture has started (best-effort, Windows)."""
    try:
        import winsound  # noqa: PLC0415

        winsound.Beep(settings.stt_beep_freq, settings.stt_beep_ms)
    except Exception:  # noqa: BLE001
        pass


class VoiceInputService:
    def __init__(
        self,
        settings: Settings,
        tts: TtsService,
        voice_ask: Callable[[str], Awaitable[None]],
        broadcast: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        self._s = settings
        self._tts = tts
        self._voice_ask = voice_ask
        self._broadcast = broadcast

        self._recognizer = None
        self._available = False
        self._capturing = False
        self._reason = "in avvio"

    async def start(self) -> None:
        if not self._s.enable_stt:
            self._reason = "disabilitato (ENABLE_STT=0)"
            await self._status()
            return
        ok, reason = _deps_available()
        if not ok:
            self._reason = reason
            logger.info("stt unavailable: %s", reason)
            await self._status()
            return
        self._available = True
        self._reason = ""
        logger.info("stt available (push-to-talk)")
        await self._status()

    async def trigger(self) -> None:
        """Run one push-to-talk capture turn (from the UI or the Space key)."""
        if not self._available or self._capturing:
            return
        if not _has_input_device():
            self._reason = "nessun microfono rilevato"
            await self._status()
            return
        if self._recognizer is None:
            self._recognizer = make_recognizer(self._s)
        self._capturing = True
        self._reason = ""
        await self._status()
        asyncio.create_task(self._run_capture(), name="stt_capture")

    async def _run_capture(self) -> None:
        try:
            text = await asyncio.to_thread(self._capture_blocking)
        except Exception:  # noqa: BLE001
            logger.exception("stt capture failed")
            text = None
        finally:
            self._capturing = False
            await self._status()
        await self._voice_ask(text or "")

    def _capture_blocking(self) -> str | None:
        _beep(self._s)
        return listen_and_transcribe(self._recognizer, self._s)

    async def stop(self) -> None:
        self._capturing = False

    def status_payload(self) -> dict:
        return {
            "enabled": self._s.enable_stt,
            "available": self._available,
            "listening": self._capturing,
            "reason": self._reason,
        }

    async def _status(self) -> None:
        await self._broadcast("stt_status", self.status_payload())
