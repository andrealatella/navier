"""Speech-to-text via SpeechRecognition and the free Google Web Speech endpoint."""

from __future__ import annotations

import logging

from ..config import Settings

logger = logging.getLogger("navier.stt")


def make_recognizer(settings: Settings):
    """Build a tuned Recognizer, reused across turns so its noise estimate adapts."""
    import speech_recognition as sr  # noqa: PLC0415

    r = sr.Recognizer()
    r.dynamic_energy_threshold = True
    r.pause_threshold = settings.stt_silence_s
    return r


def listen_and_transcribe(recognizer, settings: Settings) -> str | None:
    """Open the mic, capture one phrase (auto-endpointed), return Italian text or None."""
    import speech_recognition as sr  # noqa: PLC0415

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(
                source,
                timeout=settings.stt_listen_timeout_s,
                phrase_time_limit=settings.stt_record_max_s,
            )
    except sr.WaitTimeoutError:
        logger.info("stt: no speech (listen timeout)")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("stt mic capture failed: %s", e)
        return None

    try:
        text = recognizer.recognize_google(audio, language="it-IT")
    except sr.UnknownValueError:
        logger.info("stt: Google STT could not understand the audio")
        return None
    except sr.RequestError as e:
        logger.warning("stt: Google STT request failed: %s", e)
        return None
    return (text or "").strip() or None
