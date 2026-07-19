"""Live WebSocket endpoint `/ws/live`."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .. import __version__, runtime
from ..models import UserPosition
from ..store.hub import hub
from ..store.memory import lightning_store, serialize_strikes
from ..store.radar import radar_store

logger = logging.getLogger("navier.ws")

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await hub.connect(ws)
    await hub.send(
        ws, "hello", {"server": "navier", "version": __version__, "replay": runtime.is_replaying()}
    )
    await hub.send(ws, "lightning_batch", {"strikes": serialize_strikes(lightning_store.recent())})
    await hub.send(ws, "radar_frames", radar_store.active_payload())
    await hub.send(ws, "source_health", runtime.source_health_payload())
    await hub.send(ws, "copilot_status", runtime.copilot_status_payload())
    await hub.send(ws, "stt_status", runtime.stt_status_payload())
    await hub.send(ws, "recorder_status", runtime.recorder_status_payload())
    proc = runtime.processor()
    if proc is not None and (world := proc.latest_world_wire()) is not None:
        await hub.send(ws, "world_state", world)
    try:
        while True:
            msg = await ws.receive_json()
            type_ = msg.get("type") if isinstance(msg, dict) else None
            payload = msg.get("payload", {}) if isinstance(msg, dict) else {}

            if type_ == "ping":
                await hub.send(ws, "pong", {})
            elif type_ == "position_update":
                await _handle_position(ws, payload)
            elif type_ == "set_target":
                runtime.set_target(payload.get("cell_id"))
            elif type_ == "ask_copilot":
                await runtime.ask_copilot(str(payload.get("question", "")))
            elif type_ == "set_copilot_proactive":
                await runtime.set_copilot_proactive(bool(payload.get("on")))
            elif type_ == "set_tts":
                runtime.set_tts_enabled(bool(payload.get("enabled", True)))
            elif type_ == "push_to_talk":
                await runtime.trigger_stt()
            elif type_ == "set_recorder":
                await runtime.set_recording(bool(payload.get("on")))
            elif type_ == "open_maps":
                await _handle_open_maps(payload)
            else:
                await hub.send(ws, "echo", {"type": type_, "payload": payload})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws_live error")
    finally:
        await hub.disconnect(ws)


async def _handle_position(ws: WebSocket, payload: dict) -> None:
    """Validate and forward a client position report to the processor."""
    try:
        user = UserPosition(**payload)
    except (ValidationError, TypeError) as e:
        await hub.send(ws, "error", {"of": "position_update", "detail": str(e)})
        return
    await runtime.on_position_update(user)


async def _handle_open_maps(payload: dict) -> None:
    """Fan a navigation intent out to every client so the phone opens Google Maps."""
    from ..routing.intercept import maps_deeplink

    try:
        lat = float(payload["lat"])
        lon = float(payload["lon"])
    except (KeyError, TypeError, ValueError):
        return
    await hub.broadcast(
        "open_maps",
        {"lat": lat, "lon": lon, "label": payload.get("label"), "url": maps_deeplink(lat, lon)},
    )
