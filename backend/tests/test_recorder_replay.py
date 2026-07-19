"""Session recorder + replayer tests."""

from __future__ import annotations

import asyncio
import json

from app.store.recorder import SessionRecorder, list_sessions
from app.store.replayer import SessionReplayer, resolve_session


def test_recorder_writes_jsonl_and_ignores_health(tmp_path):
    rec = SessionRecorder(tmp_path)
    rec.record("world_state", {"a": 1})
    rec.record("source_health", {"noise": True})
    rec.record("recorder_status", {"bytes": 5})
    rec.record("lightning_batch", {"strikes": []})
    rec.close()

    events = (tmp_path / rec.name / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 2
    first = json.loads(events[0])
    assert first["type"] == "world_state" and first["payload"] == {"a": 1}
    assert "t" in first


def test_recorder_counts_and_sizes_what_it_wrote(tmp_path):
    rec = SessionRecorder(tmp_path)
    assert rec.count == 0 and rec.size_bytes == 0
    rec.record("world_state", {"a": 1})
    rec.record("source_health", {"ignored": True})
    assert rec.count == 1
    assert rec.size_bytes > 0
    before = rec.size_bytes
    rec.record("world_state", {"b": 2})
    assert rec.count == 2 and rec.size_bytes > before
    rec.close()


def test_recorder_discards_an_empty_session(tmp_path):
    rec = SessionRecorder(tmp_path)
    assert (tmp_path / rec.name).is_dir()
    rec.close()
    assert not (tmp_path / rec.name).exists()
    assert list_sessions(tmp_path) == []


def test_recorder_keeps_a_session_with_events(tmp_path):
    rec = SessionRecorder(tmp_path)
    rec.record("world_state", {"a": 1})
    rec.close()
    assert (tmp_path / rec.name / "events.jsonl").is_file()


def test_list_sessions_newest_first(tmp_path):
    r1 = SessionRecorder(tmp_path)
    r1.record("world_state", {})
    r1.close()
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["name"] == r1.name
    assert sessions[0]["size_bytes"] > 0


def test_resolve_session_dir_and_file(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    e1, f1 = resolve_session(str(tmp_path))
    e2, f2 = resolve_session(str(events))
    assert e1.name == "events.jsonl" and f1.name == "frames"
    assert e2 == events and f2.name == "frames"


def test_replayer_reemits_in_order(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            json.dumps({"t": t, "type": ty, "payload": {"n": n}})
            for t, ty, n in [
                (0, "world_state", 0),
                (60, "lightning_batch", 1),
                (120, "world_state", 2),
            ]
        ),
        encoding="utf-8",
    )
    got: list[tuple[str, int]] = []

    async def fake_broadcast(type_: str, payload: dict) -> None:
        got.append((type_, payload["n"]))

    async def drive() -> None:
        rep = SessionReplayer(str(tmp_path), fake_broadcast, speed=100.0)
        assert rep.load() == 3
        await rep.start()
        for _ in range(200):
            if len(got) >= 3:
                break
            await asyncio.sleep(0.01)
        await rep.stop()

    asyncio.run(drive())
    assert [n for _, n in got[:3]] == [0, 1, 2]
    assert got[0][0] == "world_state" and got[1][0] == "lightning_batch"


def test_replayer_frame_png_fallback(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "12345.png").write_bytes(b"PNGDATA")
    rep = SessionReplayer(str(tmp_path), lambda *_: None, speed=1.0)  # type: ignore[arg-type]
    assert rep.frame_png(12345) == b"PNGDATA"
    assert rep.frame_png(999) is None
