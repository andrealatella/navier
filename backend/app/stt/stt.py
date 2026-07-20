"""Speech-to-text via SpeechRecognition and the free Google Web Speech endpoint.
"""

from __future__ import annotations

import logging

from ..config import Settings

logger = logging.getLogger("navier.stt")

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # int16, what AudioData expects

_BLOCK_MS = 30
_CALIBRATE_S = 0.4
_THRESHOLD_FACTOR = 2.5
_THRESHOLD_FLOOR = 250.0


def make_recognizer(settings: Settings):
    """Recognizer for the Google call; capture and endpointing live here."""
    import speech_recognition as sr  # noqa: PLC0415

    return sr.Recognizer()


def _rms(block) -> float:
    """Loudness of one int16 mono block, in int16 units."""
    import numpy as np  # noqa: PLC0415

    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block.astype(np.float64)))))


def _calibrate(stream, block: int) -> float:
    """Average ambient level, sampled briefly before listening starts."""
    levels = []
    for _ in range(max(1, int(_CALIBRATE_S * SAMPLE_RATE / block))):
        data, _ = stream.read(block)
        levels.append(_rms(data[:, 0]))
    return sum(levels) / len(levels) if levels else 0.0


def _record_phrase(settings: Settings) -> bytes | None:
    """Capture one spoken phrase from the default mic.

    Waits up to `stt_listen_timeout_s` for speech to start, then records until
    `stt_silence_s` of silence or the `stt_record_max_s` cap. None if nobody
    spoke.
    """
    import numpy as np  # noqa: PLC0415
    import sounddevice as sd  # noqa: PLC0415

    block = max(1, int(SAMPLE_RATE * _BLOCK_MS / 1000))
    block_s = block / SAMPLE_RATE
    frames = []

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block
    ) as stream:
        threshold = max(_calibrate(stream, block) * _THRESHOLD_FACTOR, _THRESHOLD_FLOOR)

        waited_s = 0.0
        while True:
            data, _ = stream.read(block)
            mono = data[:, 0]
            if _rms(mono) >= threshold:
                frames.append(mono.copy())
                break
            waited_s += block_s
            if waited_s >= settings.stt_listen_timeout_s:
                logger.info("stt: no speech (listen timeout)")
                return None

        silence_s = 0.0
        spoken_s = 0.0
        while silence_s < settings.stt_silence_s and spoken_s < settings.stt_record_max_s:
            data, _ = stream.read(block)
            mono = data[:, 0]
            frames.append(mono.copy())
            spoken_s += block_s
            silence_s = silence_s + block_s if _rms(mono) < threshold else 0.0

    return np.concatenate(frames).tobytes() if frames else None


def listen_and_transcribe(recognizer, settings: Settings) -> str | None:
    """Open the mic, capture one phrase, return Italian text or None."""
    import speech_recognition as sr  # noqa: PLC0415

    try:
        raw = _record_phrase(settings)
    except Exception as e:  # noqa: BLE001
        logger.warning("stt mic capture failed: %s", e)
        return None
    if not raw:
        return None

    audio = sr.AudioData(raw, SAMPLE_RATE, SAMPLE_WIDTH)
    try:
        text = recognizer.recognize_google(audio, language="it-IT")
    except sr.UnknownValueError:
        logger.info("stt: Google STT could not understand the audio")
        return None
    except sr.RequestError as e:
        logger.warning("stt: Google STT request failed: %s", e)
        return None
    return (text or "").strip() or None
