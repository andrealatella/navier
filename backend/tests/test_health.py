"""Smoke tests: health endpoint and the WS hello/echo round-trip."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "sources_enabled" in body
    assert "blitzortung" in body["sources_enabled"]


def _recv_type(ws, type_: str, max_msgs: int = 10) -> dict:
    """Receive until a message of the given type arrives (skips the rest)."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"never received a {type_!r} message")


def test_ws_hello_and_echo() -> None:
    with client.websocket_connect("/ws/live") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["payload"]["server"] == "navier"

        assert "strikes" in _recv_type(ws, "lightning_batch")["payload"]
        assert "sources" in _recv_type(ws, "source_health")["payload"]

        ws.send_json({"type": "ping"})
        assert _recv_type(ws, "pong")["type"] == "pong"

        ws.send_json({"type": "set_mode", "payload": {"mode": "chase"}})
        echo = _recv_type(ws, "echo")
        assert echo["payload"]["type"] == "set_mode"
        assert echo["payload"]["payload"]["mode"] == "chase"
