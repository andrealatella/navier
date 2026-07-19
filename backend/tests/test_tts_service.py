"""TtsService tests: priority queue, P1 interrupt, mute, warm, graceful degrade."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import Settings
from app.models import Alert
from app.tts.service import STATIC_PHRASES, TtsService


class FakeSynth:
    def __init__(self, tmp: Path, available: bool = True) -> None:
        self.tmp = tmp
        self.calls: list[str] = []
        self.persistent: set[str] = set()
        self.pruned = False
        self._available = available

    def available(self) -> bool:
        return self._available

    def register_persistent(self, texts) -> None:
        self.persistent = set(texts)

    def prune(self) -> None:
        self.pruned = True

    def synth(self, text: str) -> Path | None:
        self.calls.append(text)
        p = self.tmp / f"{abs(hash(text))}.wav"
        p.write_bytes(b"\0" * 100)
        return p


class FakePlayer:
    def __init__(self, available: bool = True) -> None:
        self.played: list[Path] = []
        self.stops = 0
        self._available = available

    def available(self) -> bool:
        return self._available

    def play(self, path: Path) -> None:
        self.played.append(Path(path))

    def stop(self) -> None:
        self.stops += 1


def _alert(rule_id: str, priority: int, tts_text: str) -> Alert:
    return Alert(
        id=f"{rule_id}:1",
        rule_id=rule_id,
        priority=priority,
        title=rule_id,
        message="…",
        tts_text=tts_text,
    )


def _svc(tmp: Path, *, synth_ok: bool = True, player_ok: bool = True) -> tuple:
    synth = FakeSynth(tmp, available=synth_ok)
    player = FakePlayer(available=player_ok)
    svc = TtsService(Settings(enable_tts=True), synth=synth, player=player)
    return svc, synth, player


async def _drain(svc: TtsService) -> None:
    """Wait for the worker to finish everything queued so far."""
    await asyncio.wait_for(svc._queue.join(), timeout=3)


async def test_warm_registers_prunes_and_synthesizes_static_phrases(tmp_path):
    svc, synth, _ = _svc(tmp_path)
    await svc.start()
    try:
        assert synth.persistent == set(STATIC_PHRASES)
        assert synth.pruned
        assert set(STATIC_PHRASES) <= set(synth.calls)
    finally:
        await svc.stop()


async def test_speak_alerts_plays_each(tmp_path):
    svc, _, player = _svc(tmp_path)
    await svc.start()
    try:
        svc.speak_alerts([_alert("LIGHTNING_JUMP", 2, "uno"), _alert("NEW_STRONG_CELL", 3, "due")])
        await _drain(svc)
        assert len(player.played) == 2
    finally:
        await svc.stop()


async def test_copilot_line_is_spoken(tmp_path):
    svc, synth, player = _svc(tmp_path)
    await svc.start()
    try:
        svc.speak_copilot("la cella 3 si intensifica", kind="alert")
        await _drain(svc)
        assert "la cella 3 si intensifica" in synth.calls
        assert len(player.played) == 1
    finally:
        await svc.stop()


async def test_p1_interrupts_and_clears_queue(tmp_path):
    """A P1 clears everything pending and stops the current line."""
    svc, _, player = _svc(tmp_path)
    svc._available = True
    svc._queue = asyncio.PriorityQueue()

    svc.say("p2 line", priority=1_000, label="p2")
    svc.say("p3 line", priority=2_000, label="p3")
    assert svc._queue.qsize() == 2

    svc.say("FULMINI", priority=0, interrupt=True, label="LIGHTNING_NEAR")
    assert player.stops == 1
    items = []
    while not svc._queue.empty():
        items.append(svc._queue.get_nowait()[2])
    assert [i.text for i in items] == ["FULMINI"]


async def test_mute_silences_and_stops(tmp_path):
    svc, _, player = _svc(tmp_path)
    await svc.start()
    try:
        svc.set_enabled(False)
        assert player.stops >= 1
        svc.speak_alerts([_alert("LIGHTNING_NEAR", 1, "fulmini")])
        await asyncio.sleep(0.05)
        assert player.played == []
    finally:
        await svc.stop()


async def test_say_wav_bypasses_synth(tmp_path):
    svc, synth, player = _svc(tmp_path)
    await svc.start()
    try:
        ack = tmp_path / "ack.wav"
        ack.write_bytes(b"\0" * 100)
        before = list(synth.calls)
        svc.say_wav(ack, label="ack")
        await _drain(svc)
        assert player.played == [ack]
        assert synth.calls == before
    finally:
        await svc.stop()


async def test_dormant_without_system_tts(tmp_path):
    """No system voice -> the service stays dormant and speaking is a no-op."""
    svc, _, player = _svc(tmp_path, synth_ok=False)
    await svc.start()
    try:
        assert svc.available is False
        svc.speak_alerts([_alert("LIGHTNING_NEAR", 1, "fulmini")])
        await asyncio.sleep(0.05)
        assert player.played == []
    finally:
        await svc.stop()
