"""App runtime wiring: ingestors → store → WebSocket broadcast."""

from __future__ import annotations

import asyncio
import logging

from .config import settings
from .copilot.service import Copilot
from .ingest.base import SourceHealth
from .ingest.blitzortung import BlitzortungIngestor
from .ingest.dpc_allerte import DpcAllerteIngestor
from .ingest.dpc_products import DpcProductsIngestor
from .ingest.dpc_radar import DpcRadarIngestor
from .ingest.fake import FakeLightningIngestor
from .ingest.gpsd import GpsdIngestor
from .ingest.manager import IngestorManager
from .ingest.openmeteo import OpenMeteoIngestor
from .ingest.outlook import OutlookIngestor
from .ingest.rainviewer import RainViewerIngestor
from .models import LightningStrike, UserPosition
from .processing.processor import Processor
from .store.allerte import allerte_store
from .store.hub import hub
from .store.memory import lightning_store, serialize_strikes
from .store.meteo import meteo_store
from .store.outlook import outlook_store
from .store.radar import RadarFrameEntry, radar_store
from .store.recorder import SessionRecorder
from .store.replayer import SessionReplayer
from .stt.service import VoiceInputService
from .tts.service import TtsService

logger = logging.getLogger("navier.runtime")

_manager: IngestorManager | None = None
_health_task: asyncio.Task | None = None
_processor: Processor | None = None
_copilot: Copilot | None = None
_tts: TtsService | None = None
_stt: VoiceInputService | None = None
_recorder: SessionRecorder | None = None
_replayer: SessionReplayer | None = None


async def _strike_sink(strikes: list[LightningStrike]) -> None:
    """Store a batch and fan it out to all clients as `lightning_batch`."""
    lightning_store.add(strikes)
    await hub.broadcast("lightning_batch", {"strikes": serialize_strikes(strikes)})


async def _grid_sink(ts_ms: int, grid, transform) -> None:
    """Feed a fresh DPC dBZ grid to the cell tracker."""
    if _processor is not None:
        await _processor.on_radar_grid(ts_ms, grid, transform)


async def _poh_sink(grid) -> None:
    """Feed a fresh DPC POH grid to the processor for the hail rule."""
    if _processor is not None:
        await _processor.on_poh_grid(grid)


async def _sri_sink(grid) -> None:
    """Feed a fresh DPC SRI grid to the processor for FLASH_FLOOD."""
    if _processor is not None:
        await _processor.on_sri_grid(grid)


async def on_position_update(user: UserPosition) -> None:
    """Client-reported GPS/manual position → processor."""
    if _processor is not None:
        await _processor.on_position(user)


def set_target(cell_id: int | None) -> None:
    if _processor is not None:
        _processor.set_target(cell_id)


def processor() -> Processor | None:
    return _processor


async def _broadcast_radar() -> None:
    """Push the currently-active radar source's frame list to every client."""
    await hub.broadcast("radar_frames", radar_store.active_payload())


async def _dpc_frame_sink(entry: RadarFrameEntry) -> None:
    """Store one DPC image frame and re-broadcast the active animation."""
    radar_store.add_frame(entry)
    await _broadcast_radar()


async def _rainviewer_sink(entries: list[RadarFrameEntry]) -> None:
    """Replace the RainViewer ring and re-broadcast (fallback may be showing)."""
    radar_store.replace("rainviewer", entries)
    await _broadcast_radar()


def _health_dict(h: SourceHealth) -> dict:
    return {
        "name": h.name,
        "state": h.state.value,
        "detail": h.detail,
        "age_s": h.age_s,
        "events_total": h.events_total,
    }


def source_health_payload() -> dict:
    """Current source-health snapshot (also sent to a client on connect)."""
    sources = [_health_dict(h) for h in _manager.health()] if _manager else []
    return {
        "sources": sources,
        "lightning_count": lightning_store.count(),
        "radar": {
            "active": radar_store.active_source(),
            "dpc_frames": radar_store.frame_count("dpc"),
            "rainviewer_frames": radar_store.frame_count("rainviewer"),
        },
        "meteo": {
            "available": meteo_store.available,
            "updated_ms": int(meteo_store.updated_at.timestamp() * 1000)
            if meteo_store.updated_at
            else None,
        },
        "allerte": {
            "available": allerte_store.available,
            "issued": allerte_store.issued,
        },
    }


def _build_manager() -> IngestorManager:
    m = IngestorManager()
    if settings.enable_fake_lightning:
        m.register(FakeLightningIngestor(_strike_sink))
        logger.info("lightning source: FAKE generator (dev)")
    elif settings.enable_blitzortung:
        m.register(BlitzortungIngestor(_strike_sink, settings))
        logger.info("lightning source: Blitzortung (live)")
    else:
        logger.info("lightning source: none enabled")

    if settings.enable_dpc_radar:
        m.register(DpcRadarIngestor(_dpc_frame_sink, settings, radar_store, grid_sink=_grid_sink))
        logger.info("radar source: DPC (primary)")
    if settings.enable_rainviewer:
        m.register(RainViewerIngestor(_rainviewer_sink, settings))
        role = "fallback" if settings.enable_dpc_radar else "primary"
        logger.info("radar source: RainViewer (%s)", role)

    if settings.enable_dpc_products:
        m.register(DpcProductsIngestor(_poh_sink, _sri_sink, settings))
        logger.info("radar products: DPC POH + SRI (alert rules)")

    if settings.enable_openmeteo:
        m.register(OpenMeteoIngestor(meteo_store, settings))
        logger.info("environment source: Open-Meteo (%s)", settings.openmeteo_model)

    if settings.enable_dpc_allerte:
        m.register(DpcAllerteIngestor(allerte_store, settings))
        logger.info("official alerts source: DPC criticality bulletins")

    if settings.enable_pretemp:
        m.register(OutlookIngestor(outlook_store, settings, analyzer=analyze_pretemp_image))
        logger.info("planning outlooks source: PRETEMP + ESTOFEX")

    if settings.enable_gpsd:
        m.register(GpsdIngestor(on_position_update, settings.gpsd_host, settings.gpsd_port))
        logger.info("GPS source: gpsd %s:%d", settings.gpsd_host, settings.gpsd_port)
    return m


async def _health_loop() -> None:
    while True:
        await asyncio.sleep(3.0)
        try:
            await hub.broadcast("source_health", source_health_payload())
            if _recorder is not None:
                await hub.broadcast("recorder_status", recorder_status_payload())
        except Exception:  # noqa: BLE001
            logger.debug("source_health broadcast failed")


async def start() -> None:
    """Start the backend: replay a recorded session if REPLAY_FILE is set, else go live."""
    if settings.replay_file and await _start_replay():
        return
    await _start_live()


async def _start_replay() -> bool:
    """Replay mode: re-broadcast a recorded session; no ingestors/processor."""
    global _replayer
    replayer = SessionReplayer(settings.replay_file, hub.broadcast, settings.replay_speed)
    await replayer.start()
    if not replayer.playing:
        logger.error(
            "REPLAY_FILE=%r non riproducibile: passo in modalita' live", settings.replay_file
        )
        await replayer.stop()
        return False
    _replayer = replayer
    logger.info("REPLAY mode: %s (%.2fx)", settings.replay_file, settings.replay_speed)
    return True


async def _start_live() -> None:
    global _manager, _health_task, _processor, _copilot, _tts, _stt, _recorder
    if settings.enable_recorder and settings.recorder_autostart:
        start_recording()
    _tts = TtsService(settings)
    await _tts.start()
    _processor = Processor(
        settings, hub.broadcast, lightning_store, radar_store, meteo_store, allerte_store
    )
    _copilot = Copilot(settings, hub.broadcast, speak=_tts.speak_copilot)

    def _world_listener(ws, active, fired) -> None:
        _copilot.on_world(ws, active, fired)
        _tts.speak_alerts(fired)

    _processor.set_world_listener(_world_listener)
    await _copilot.start()
    await _processor.start()
    _stt = VoiceInputService(settings, _tts, _copilot.voice_ask, hub.broadcast)
    await _stt.start()
    _manager = _build_manager()
    await _manager.start()
    _health_task = asyncio.create_task(_health_loop(), name="source_health")


async def stop() -> None:
    global _manager, _health_task, _processor, _copilot, _tts, _stt, _recorder, _replayer
    if _replayer:
        await _replayer.stop()
        _replayer = None
    if _health_task:
        _health_task.cancel()
        _health_task = None
    if _manager:
        await _manager.stop()
        _manager = None
    if _stt:
        await _stt.stop()
        _stt = None
    if _processor:
        await _processor.stop()
        _processor = None
    if _copilot:
        await _copilot.stop()
        _copilot = None
    if _tts:
        await _tts.stop()
        _tts = None
    if _recorder:
        hub.set_recorder(None)
        _recorder.close()
        _recorder = None


def copilot() -> Copilot | None:
    return _copilot


def copilot_status_payload() -> dict:
    """Current co-pilot status for the UI (sent on connect). Safe before start."""
    if _copilot is not None:
        return _copilot.status_payload()
    return {"enabled": False, "available": False, "reason": "in avvio", "busy": False}


async def ask_copilot(question: str) -> None:
    """Route an operator question to the co-pilot (from the WS)."""
    if _copilot is not None:
        await _copilot.ask(question)


async def set_copilot_proactive(on: bool) -> None:
    """Enable/disable the co-pilot's proactive ticker at runtime (UI toggle)."""
    if _copilot is not None:
        await _copilot.set_proactive(on)


async def analyze_pretemp_image(image_bytes: bytes, mime_type: str) -> dict | None:
    """Vision-read the PRETEMP map via the co-pilot; None if unavailable."""
    if _copilot is not None:
        return await _copilot.analyze_pretemp(image_bytes, mime_type)
    return None


def tts() -> TtsService | None:
    return _tts


def set_tts_enabled(on: bool) -> None:
    """Mute/unmute the backend voice pipeline from the UI."""
    if _tts is not None:
        _tts.set_enabled(on)


def stt() -> VoiceInputService | None:
    return _stt


def stt_status_payload() -> dict:
    """Current voice-input status for the UI (sent on connect). Safe before start."""
    if _stt is not None:
        return _stt.status_payload()
    return {"enabled": False, "available": False, "listening": False, "reason": "in avvio"}


async def trigger_stt() -> None:
    """Run one push-to-talk capture turn (from the UI or the Space key)."""
    if _stt is not None:
        await _stt.trigger()




def start_recording() -> bool:
    """Begin taping this session to data/sessions/. True if recording afterwards."""
    global _recorder
    if _recorder is not None:
        return True
    if not settings.enable_recorder or is_replaying():
        return False
    try:
        _recorder = SessionRecorder(settings.sessions_path)
        hub.set_recorder(_recorder.record)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("could not start session recorder: %s", e)
        _recorder = None
        return False


def stop_recording() -> None:
    """Close the current session, keeping what was taped so far."""
    global _recorder
    if _recorder is None:
        return
    hub.set_recorder(None)
    _recorder.close()
    _recorder = None


def recorder_status_payload() -> dict:
    """Recording state for the UI (sent on connect + after each toggle)."""
    rec = _recorder
    return {
        "available": settings.enable_recorder and not is_replaying(),
        "recording": rec is not None,
        "session": rec.name if rec is not None else None,
        "events": rec.count if rec is not None else 0,
        "bytes": rec.size_bytes if rec is not None else 0,
    }


async def set_recording(on: bool) -> None:
    """UI toggle: start/stop recording, then tell every client the new state."""
    if on:
        start_recording()
    else:
        stop_recording()
    await hub.broadcast("recorder_status", recorder_status_payload())


def manager() -> IngestorManager | None:
    return _manager


def is_replaying() -> bool:
    return _replayer is not None


def replay_frame_png(ts_ms: int) -> bytes | None:
    """Serve a recorded radar frame during replay (fallback for the frame endpoint)."""
    return _replayer.frame_png(ts_ms) if _replayer is not None else None


def list_recorded_sessions() -> dict:
    """Recorded sessions + current recording, for `GET /api/sessions`."""
    from .store.recorder import list_sessions

    return {
        "replaying": is_replaying(),
        "recording": _recorder.name if _recorder is not None else None,
        "sessions": list_sessions(settings.sessions_path),
    }
