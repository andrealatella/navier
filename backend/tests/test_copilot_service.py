"""Co-pilot orchestrator: chat, quota degradation, dedup, priority."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.config import Settings
from app.copilot.budget import Budget
from app.copilot.gemini import GeminiResult
from app.copilot.prompts import CopilotReply
from app.copilot.service import Copilot, _Req
from app.models import Alert, CellSnapshot, Motion, UserPosition
from app.processing.world import WorldState

NOW = datetime(2026, 7, 13, 15, 42, tzinfo=UTC)


class FakeClient:
    """Stand-in for GeminiClient: returns canned results, records calls."""

    def __init__(self, results) -> None:
        self._results = results
        self.calls: list[tuple[str, str]] = []

    async def generate(self, model: str, contents: str) -> GeminiResult:
        self.calls.append((model, contents))
        if isinstance(self._results, list):
            return self._results.pop(0)
        return self._results


def _world() -> WorldState:
    cell = CellSnapshot(
        id=3,
        ts=NOW,
        polygon={
            "type": "Polygon",
            "coordinates": [[[8.6, 45.0], [8.7, 45.0], [8.6, 45.1], [8.6, 45.0]]],
        },
        centroid=(8.6, 45.0),
        area_km2=100,
        max_dbz=58,
        motion=Motion(speed_kmh=35, bearing_deg=110),
        severity=82,
        lightning_rate_min=41,
        trend="up",
    )
    user = UserPosition(ts=NOW, lat=44.71, lon=8.62, source="manual")
    return WorldState(ts=NOW, cells=[cell], user=user, radar_age_s=140, lightning_age_s=3)


def _make(client, *, daily_limit=100, min_interval_s=45, speak=None):
    sent: list[tuple[str, dict]] = []

    async def broadcast(type_: str, payload: dict) -> None:
        sent.append((type_, payload))

    cop = Copilot(Settings(), broadcast, speak=speak)
    cop._client = client
    cop._budget = Budget(daily_limit, min_interval_s=min_interval_s)
    cop._queue = asyncio.PriorityQueue()
    cop._available = True
    cop._enabled = True
    cop._reason = ""
    cop._ws = _world()
    return cop, sent


def _msgs(sent, kind=None):
    out = [p for t, p in sent if t == "copilot_msg"]
    return [m for m in out if kind is None or m.get("kind") == kind]


async def test_chat_reply_broadcasts_and_counts():
    reply = CopilotReply(
        reply="La cella 3 è forte, tieniti a sud.",
        urgency="warning",
        speak=True,
        tts_text="Cella 3 forte.",
    )
    cop, sent = _make(FakeClient(GeminiResult(reply=reply, tokens=80)))
    await cop._handle(_Req(kind="chat", question="che rischi ha la 3?"))
    chat = _msgs(sent, "chat")
    assert len(chat) == 1
    assert chat[0]["role"] == "assistant" and chat[0]["speak"] is True
    assert cop.status_payload()["calls_today"] == 1
    model, contents = cop._client.calls[0]
    assert model == cop._s.gemini_model_chat and "SNAPSHOT" in contents


async def test_quota_error_degrades_without_crashing():
    cop, sent = _make(FakeClient(GeminiResult(error="quota", retry_after_s=30)))
    await cop._handle(_Req(kind="chat", question="ciao"))
    assert any(m["role"] == "system" for m in _msgs(sent))
    st = cop.status_payload()
    assert st["quota_exhausted"] is True
    assert st["calls_today"] == 0


async def test_proactive_dedup_suppresses_identical_reply():
    reply = CopilotReply(
        reply="Situazione stabile.", urgency="info", speak=True, tts_text="Stabile."
    )
    cop, sent = _make(
        FakeClient([GeminiResult(reply=reply), GeminiResult(reply=reply.model_copy())])
    )
    await cop._handle(_Req(kind="proactive"))
    await cop._handle(_Req(kind="proactive"))
    assert len(_msgs(sent, "proactive")) == 1


async def test_proactive_silence_is_not_broadcast():
    empty = CopilotReply(reply="", urgency="info", speak=False, tts_text="")
    cop, sent = _make(FakeClient(GeminiResult(reply=empty)))
    await cop._handle(_Req(kind="proactive"))
    assert _msgs(sent, "proactive") == []


async def test_ask_when_unavailable_emits_system_note():
    sent: list[tuple[str, dict]] = []

    async def broadcast(type_, payload):
        sent.append((type_, payload))

    cop = Copilot(Settings(), broadcast)
    await cop.ask("quale cella conviene?")
    assert any(t == "copilot_msg" and p["role"] == "system" for t, p in sent)


def test_on_world_enqueues_alert_commentary():
    cop, _ = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    p1 = Alert(
        id="LIGHTNING_NEAR:1",
        rule_id="LIGHTNING_NEAR",
        priority=1,
        title="t",
        message="m",
        tts_text="v",
    )
    p3 = Alert(
        id="NEW_STRONG_CELL:1",
        rule_id="NEW_STRONG_CELL",
        priority=3,
        title="t",
        message="m",
        tts_text="v",
    )
    cop.on_world(_world(), [p1, p3], [p1, p3])
    assert cop._queue.qsize() == 1
    prio, _seq, req = cop._queue.get_nowait()
    assert req.kind == "alert" and prio == 1


async def test_set_proactive_toggles_ticker_and_status():
    cop, _ = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    assert cop.status_payload()["proactive"] is False
    await cop.set_proactive(True)
    assert cop.status_payload()["proactive"] is True
    assert cop._ticker_task is not None
    await cop.set_proactive(False)
    assert cop.status_payload()["proactive"] is False
    assert cop._ticker_task is None


def test_data_stale_alert_is_not_commented():
    cop, _ = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    stale = Alert(
        id="DATA_STALE:1", rule_id="DATA_STALE", priority=2, title="t", message="m", tts_text="v"
    )
    cop.on_world(_world(), [stale], [stale])
    assert cop._queue.qsize() == 0


def test_alert_commentary_rate_limited_per_rule():
    cop, _ = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    a1 = Alert(
        id="HAIL_RISK:1", rule_id="HAIL_RISK", priority=2, title="t", message="m", tts_text="v"
    )
    a2 = Alert(
        id="HAIL_RISK:2", rule_id="HAIL_RISK", priority=2, title="t", message="m", tts_text="v"
    )
    cop.on_world(_world(), [a1], [a1])
    cop.on_world(_world(), [a2], [a2])
    assert cop._queue.qsize() == 1


def test_priority_user_served_before_proactive():
    cop, _ = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    cop._enqueue(2, _Req(kind="proactive"))
    cop._enqueue(0, _Req(kind="chat", question="q"))
    _prio, _seq, first = cop._queue.get_nowait()
    assert first.kind == "chat"


async def test_voice_ask_shows_transcript_and_asks():
    cop, sent = _make(FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))))
    await cop.voice_ask("quale cella conviene?")
    voice = _msgs(sent, "voice")
    assert len(voice) == 1
    assert voice[0]["role"] == "user" and voice[0]["reply"] == "quale cella conviene?"
    assert cop._queue.qsize() == 1
    _prio, _seq, req = cop._queue.get_nowait()
    assert req.kind == "chat" and req.question == "quale cella conviene?"


async def test_voice_ask_empty_transcript_speaks_failure():
    spoken: list[tuple[str, str]] = []
    cop, sent = _make(
        FakeClient(GeminiResult(reply=CopilotReply(reply="x", tts_text="x"))),
        speak=lambda text, kind: spoken.append((text, kind)),
    )
    await cop.voice_ask("")
    assert spoken and "capito" in spoken[0][0].lower()
    assert cop._queue.qsize() == 0
    assert _msgs(sent, "voice") == []
