"""Co-pilot orchestrator: snapshot + budget + Gemini + broadcast."""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from ..config import Settings
from ..models import Alert
from ..processing.world import WorldState
from .budget import Budget
from .prompts import alert_contents, chat_contents, proactive_contents
from .snapshot import build_snapshot

logger = logging.getLogger("navier.copilot")

_PRIO_USER = 0
_PRIO_ALERT = 1
_PRIO_PROACTIVE = 2

_NO_COMMENT_RULES = {"DATA_STALE", "LIGHTNING_JUMP"}
_ALERT_COMMENT_GAP_S = 600.0


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(order=False)
class _Req:
    kind: str
    question: str | None = None
    alert: Alert | None = None


class Copilot:
    def __init__(self, settings: Settings, broadcast, speak=None) -> None:
        self._s = settings
        self._broadcast = broadcast
        self._speak = speak

        self._enabled = False
        self._available = False
        self._reason = "in avvio"
        self._busy = False

        self._client = None
        self._budget: Budget | None = None
        self._queue: asyncio.PriorityQueue | None = None
        self._seq = itertools.count()
        self._worker_task: asyncio.Task | None = None
        self._ticker_task: asyncio.Task | None = None

        self._ws: WorldState | None = None
        self._active_alerts: list[Alert] = []
        self._target_cell_id: int | None = None

        self._last_situation_sig: tuple | None = None
        self._last_proactive_reply: str | None = None
        self._history: deque[tuple[str, str]] = deque(maxlen=4)
        self._proactive_on = False
        self._alert_commented: dict[str, datetime] = {}

    async def start(self) -> None:
        if not self._s.enable_copilot:
            self._reason = "disabilitato (ENABLE_COPILOT=0)"
            logger.info("copilot disabled by flag")
            await self._broadcast_status()
            return
        if not self._s.gemini_api_key:
            self._reason = "manca GEMINI_API_KEY"
            logger.info("copilot dormant: no GEMINI_API_KEY (the app runs without it)")
            await self._broadcast_status()
            return
        try:
            from .gemini import GeminiClient

            self._client = GeminiClient(self._s)
        except Exception as e:  # noqa: BLE001
            self._reason = "SDK google-genai non disponibile"
            logger.warning("copilot dormant: %s", e)
            await self._broadcast_status()
            return

        self._budget = Budget(
            self._s.copilot_daily_limit,
            min_interval_s=self._s.copilot_min_interval_s,
            state_path=self._s.copilot_state_path,
        )
        self._queue = asyncio.PriorityQueue()
        self._enabled = True
        self._available = True
        self._reason = ""
        self._proactive_on = self._s.copilot_proactive
        self._worker_task = asyncio.create_task(self._worker(), name="copilot_worker")
        if self._proactive_on:
            self._ticker_task = asyncio.create_task(self._ticker(), name="copilot_ticker")
        logger.info(
            "copilot enabled: chat=%s ticker=%s (proactive=%s)",
            self._s.gemini_model_chat,
            self._s.gemini_model_ticker,
            self._proactive_on,
        )
        await self._broadcast_status()

    async def set_proactive(self, on: bool) -> None:
        """Enable/disable the periodic proactive ticker at runtime (UI toggle)."""
        if not self._available:
            return
        if on == self._proactive_on:
            return
        self._proactive_on = on
        if on:
            self._last_situation_sig = None
            self._ticker_task = asyncio.create_task(self._ticker(), name="copilot_ticker")
            logger.info("copilot proactive ON (every %ds)", self._s.copilot_min_interval_s)
        elif self._ticker_task is not None:
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._ticker_task = None
            logger.info("copilot proactive OFF")
        await self._broadcast_status()

    async def stop(self) -> None:
        for task in (self._worker_task, self._ticker_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._worker_task = self._ticker_task = None

    def on_world(
        self, ws: WorldState, active_alerts: list[Alert], fired_alerts: list[Alert]
    ) -> None:
        """Processor hook (sync, hot path): store the world, enqueue alert commentary."""
        self._ws = ws
        self._active_alerts = active_alerts
        self._target_cell_id = ws.target_cell_id
        if not self._available or self._queue is None:
            return
        now = _now()
        for a in fired_alerts:
            if a.priority not in (1, 2) or a.rule_id in _NO_COMMENT_RULES:
                continue
            last = self._alert_commented.get(a.rule_id)
            if last is not None and (now - last).total_seconds() < _ALERT_COMMENT_GAP_S:
                continue
            self._alert_commented[a.rule_id] = now
            self._enqueue(_PRIO_ALERT, _Req(kind="alert", alert=a))

    async def ask(self, question: str) -> None:
        """Operator question from the WS. Highest priority."""
        question = (question or "").strip()
        if not question:
            return
        if not self._available or self._queue is None:
            await self._emit_system(f"Co-pilota non disponibile: {self._reason}.")
            return
        self._enqueue(_PRIO_USER, _Req(kind="chat", question=question))

    async def voice_ask(self, text: str) -> None:
        """Push-to-talk turn: take the transcribed text and ask."""
        text = (text or "").strip()
        if not text:
            self._say("Non ho capito, puoi ripetere?")
            await self._emit_system("Voce: non ho capito la domanda.")
            return
        if not self._available:
            self._say("Co-pilota non disponibile.")
            await self._emit_system(f"Voce: co-pilota non disponibile ({self._reason}).")
            return
        await self._broadcast(
            "copilot_msg",
            {
                "id": f"v{next(self._seq)}",
                "role": "user",
                "kind": "voice",
                "reply": text,
                "urgency": "info",
                "speak": False,
                "tts_text": "",
                "ts": int(_now().timestamp() * 1000),
            },
        )
        await self.ask(text)

    async def analyze_pretemp(
        self, image_bytes: bytes, mime_type: str = "image/png"
    ) -> dict | None:
        """Vision-read the PRETEMP outlook map into {level, zones, summary}."""
        if not self._available or self._client is None or self._budget is None:
            return None
        now = _now()
        ok, _reason = self._budget.allow(now)
        if not ok:
            return None
        self._busy = True
        await self._broadcast_status()
        try:
            extract = await self._client.extract_outlook(image_bytes, mime_type)
        finally:
            self._busy = False
        if extract is None:
            await self._broadcast_status()
            return None
        self._budget.record_call(now)
        await self._broadcast_status()
        return {"level": extract.level, "zones": extract.zones, "summary": extract.summary}

    def _say(self, text: str) -> None:
        """Speak a canned line straight through the voice pipeline (voice-input feedback)."""
        if self._speak is not None:
            try:
                self._speak(text, "alert")
            except Exception:  # noqa: BLE001
                logger.exception("copilot _say failed")

    def _enqueue(self, prio: int, req: _Req) -> None:
        assert self._queue is not None
        self._queue.put_nowait((prio, next(self._seq), req))

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(self._s.copilot_min_interval_s)
            try:
                if self._ws is None or self._budget is None:
                    continue
                if not self._budget.proactive_ready(_now()):
                    continue
                sig = self._situation_sig(self._ws)
                if sig == self._last_situation_sig:
                    continue
                self._last_situation_sig = sig
                self._enqueue(_PRIO_PROACTIVE, _Req(kind="proactive"))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("copilot ticker failed")

    @staticmethod
    def _situation_sig(ws: WorldState) -> tuple:
        """Coarse signature of the situation; changes trigger a proactive comment."""
        cells = tuple(
            sorted(
                (c.id, c.severity // 10, c.trend, "j" if "lightning_jump" in c.flags else "")
                for c in ws.cells
            )
        )
        return (cells, ws.user is not None)

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            _prio, _seq, req = await self._queue.get()
            try:
                await self._handle(req)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("copilot turn failed")
            finally:
                self._queue.task_done()

    async def _handle(self, req: _Req) -> None:
        assert self._client is not None and self._budget is not None
        now = _now()
        ok, reason = self._budget.allow(now)
        if not ok:
            await self._broadcast_status()
            if req.kind == "chat":
                await self._emit_system(_rest_message(reason))
            return

        snap = self._snapshot()
        if req.kind == "chat":
            model = self._s.gemini_model_chat
            contents = chat_contents(snap, req.question or "", history=list(self._history))
        elif req.kind == "alert":
            model = self._s.gemini_model_chat
            a = req.alert
            contents = alert_contents(snap, a.rule_id, a.priority, a.message)
        else:
            model = self._s.gemini_model_ticker
            contents = proactive_contents(snap)

        self._busy = True
        await self._broadcast_status()
        result = await self._client.generate(model, contents)
        self._busy = False

        if result.error == "quota":
            self._budget.record_quota_error(now, result.retry_after_s)
            await self._broadcast_status()
            if req.kind == "chat":
                await self._emit_system(_rest_message("quota"))
            return
        if not result.ok:
            await self._broadcast_status()
            if req.kind == "chat":
                await self._emit_system("Non riesco a contattare il co-pilota in questo momento.")
            return

        self._budget.record_call(now)
        reply = result.reply

        if req.kind == "proactive":
            said_nothing = not reply.speak and not reply.reply.strip()
            if said_nothing or reply.reply.strip() == (self._last_proactive_reply or ""):
                await self._broadcast_status()
                return
            self._last_proactive_reply = reply.reply.strip()

        if req.kind == "chat":
            self._history.append(("user", req.question or ""))
            self._history.append(("model", reply.reply))

        await self._emit_reply(req.kind, reply, tokens=result.tokens)
        await self._broadcast_status()

    def _snapshot(self) -> dict:
        if self._ws is None:
            return {
                "t": _now().isoformat(timespec="seconds"),
                "cells": [],
                "note": "nessun dato ricevuto ancora",
            }
        alerts = [{"rule_id": a.rule_id, "priority": a.priority} for a in self._active_alerts]
        from ..store.outlook import outlook_store

        return build_snapshot(
            self._ws,
            target_cell_id=self._target_cell_id,
            alerts_active=alerts,
            outlook=outlook_store.pretemp_level(),
        )

    async def _emit_reply(self, kind: str, reply, tokens: int | None) -> None:
        await self._broadcast(
            "copilot_msg",
            {
                "id": f"c{next(self._seq)}",
                "role": "assistant",
                "kind": kind,
                "reply": reply.reply,
                "urgency": reply.urgency,
                "speak": reply.speak,
                "tts_text": reply.tts_text,
                "tokens": tokens,
                "ts": int(_now().timestamp() * 1000),
            },
        )
        if reply.speak and self._speak is not None:
            try:
                self._speak(reply.tts_text or reply.reply, kind)
            except Exception:  # noqa: BLE001
                logger.exception("copilot speak failed")

    async def _emit_system(self, text: str) -> None:
        """A non-AI system note in the chat (degradation, quota) - never spoken."""
        await self._broadcast(
            "copilot_msg",
            {
                "id": f"s{next(self._seq)}",
                "role": "system",
                "kind": "system",
                "reply": text,
                "urgency": "info",
                "speak": False,
                "tts_text": "",
                "ts": int(_now().timestamp() * 1000),
            },
        )

    def status_payload(self) -> dict:
        """Current co-pilot status for the UI (also sent to a client on connect)."""
        payload = {
            "enabled": self._enabled,
            "available": self._available,
            "reason": self._reason,
            "busy": self._busy,
            "proactive": self._proactive_on and self._available,
            "model": self._s.gemini_model_chat,
        }
        if self._budget is not None:
            payload.update(self._budget.status(_now()))
        return payload

    async def _broadcast_status(self) -> None:
        await self._broadcast("copilot_status", self.status_payload())


def _rest_message(reason: str) -> str:
    if reason == "daily_limit":
        return "Co-pilota a riposo: quota giornaliera esaurita. Torna operativo domani."
    return "Co-pilota a riposo: quota momentaneamente esaurita. Riprovo tra poco."
