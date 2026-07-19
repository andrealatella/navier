"""Manual session recording: the runtime start/stop toggle."""

from __future__ import annotations

import asyncio

import pytest

from app import runtime
from app.config import settings
from app.store.hub import hub


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """Point the recorder at a temp dir and guarantee it's stopped afterwards."""
    monkeypatch.setattr(settings, "sessions_dir", str(tmp_path))
    monkeypatch.setattr(settings, "enable_recorder", True)
    yield tmp_path
    runtime.stop_recording()
    hub.set_recorder(None)


def test_not_recording_by_default(sessions_dir):
    status = runtime.recorder_status_payload()
    assert status["recording"] is False
    assert status["session"] is None
    assert status["available"] is True
    assert list(sessions_dir.iterdir()) == []


def test_start_recording_creates_a_session(sessions_dir):
    assert runtime.start_recording() is True
    status = runtime.recorder_status_payload()
    assert status["recording"] is True
    assert status["session"] is not None
    assert (sessions_dir / status["session"]).is_dir()


def test_start_is_idempotent(sessions_dir):
    runtime.start_recording()
    first = runtime.recorder_status_payload()["session"]
    runtime.start_recording()
    assert runtime.recorder_status_payload()["session"] == first
    assert len(list(sessions_dir.iterdir())) == 1


def test_stop_keeps_what_was_taped(sessions_dir):
    runtime.start_recording()
    name = runtime.recorder_status_payload()["session"]
    asyncio.run(hub.broadcast("world_state", {"cells": []}))
    runtime.stop_recording()

    assert runtime.recorder_status_payload()["recording"] is False
    events = sessions_dir / name / "events.jsonl"
    assert events.is_file() and events.read_text(encoding="utf-8").strip()


def test_stop_without_recording_is_safe(sessions_dir):
    runtime.stop_recording()
    assert runtime.recorder_status_payload()["recording"] is False


def test_disabled_recorder_refuses_to_start(sessions_dir, monkeypatch):
    monkeypatch.setattr(settings, "enable_recorder", False)
    assert runtime.start_recording() is False
    status = runtime.recorder_status_payload()
    assert status["available"] is False and status["recording"] is False
    assert list(sessions_dir.iterdir()) == []


def test_toggle_broadcasts_the_new_state(sessions_dir):
    seen: list[tuple[str, dict]] = []

    async def drive():
        original = hub.broadcast

        async def spy(type_, payload=None):
            seen.append((type_, payload or {}))
            await original(type_, payload)

        hub.broadcast = spy  # type: ignore[method-assign]
        try:
            await runtime.set_recording(True)
            await runtime.set_recording(False)
        finally:
            hub.broadcast = original  # type: ignore[method-assign]

    asyncio.run(drive())
    statuses = [p for t, p in seen if t == "recorder_status"]
    assert len(statuses) == 2
    assert statuses[0]["recording"] is True
    assert statuses[1]["recording"] is False


def test_never_tapes_a_replay(sessions_dir, monkeypatch):
    monkeypatch.setattr(runtime, "is_replaying", lambda: True)
    assert runtime.start_recording() is False
    assert runtime.recorder_status_payload()["available"] is False
