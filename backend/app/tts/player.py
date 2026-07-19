"""Interruptible WAV playback through the system speakers."""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from ..config import Settings

logger = logging.getLogger("navier.tts.player")


class Player:
    """Thin interruptible wrapper over sounddevice. Shared by the service worker."""

    def __init__(self, settings: Settings) -> None:
        self._device = _parse_device(settings.tts_output_device)
        self._sd = None

    def _ensure_sd(self):
        if self._sd is None:
            import sounddevice as sd  # noqa: PLC0415

            self._sd = sd
        return self._sd

    def available(self) -> bool:
        try:
            self._ensure_sd()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("audio playback unavailable: %s", e)
            return False

    def play(self, path: Path) -> None:
        """Blocking playback; returns when the clip finishes or stop() is called."""
        sd = self._ensure_sd()
        data, rate = _read_wav(path)
        sd.play(data, samplerate=rate, device=self._device)
        sd.wait()

    def stop(self) -> None:
        """Interrupt whatever is playing right now (thread-safe w.r.t. play())."""
        if self._sd is not None:
            self._sd.stop()


def _parse_device(spec: str):
    """sounddevice device: an int index, a name substring, or None for the default."""
    spec = (spec or "").strip()
    if not spec:
        return None
    return int(spec) if spec.isdigit() else spec


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a PCM WAV into an int16 array shaped (frames, channels)."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        frames = w.readframes(w.getnframes())
    data = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate
