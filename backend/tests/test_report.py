"""Post-chase session report tests."""

from __future__ import annotations

import json

from app.store.recorder import SessionRecorder
from app.store.report import build_report


def _write(session_dir, events):
    path = session_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _cell_fc(cells):
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": p} for p in cells],
    }


def test_report_none_for_missing_session(tmp_path):
    assert build_report(tmp_path / "nope") is None


def test_report_distance_cells_alerts(tmp_path):
    session = tmp_path / "session_x"
    events = [
        {
            "t": 0,
            "type": "world_state",
            "payload": {
                "cells": _cell_fc(
                    [
                        {"id": 1, "max_dbz": 52.0, "severity": 60, "flags": []},
                        {"id": 2, "max_dbz": 47.0, "severity": 40, "flags": ["lightning_jump"]},
                    ]
                ),
                "user": {"lat": 45.0, "lon": 9.0},
                "alerts_active": [
                    {
                        "id": "a1",
                        "rule_id": "HAIL_RISK",
                        "priority": 2,
                        "title": "Grandine",
                        "message": "x",
                    }
                ],
            },
        },
        {
            "t": 30_000,
            "type": "lightning_batch",
            "payload": {"strikes": [{"lat": 45.02, "lon": 9.0}]},
        },
        {
            "t": 60_000,
            "type": "world_state",
            "payload": {
                "cells": _cell_fc(
                    [{"id": 1, "max_dbz": 61.0, "severity": 85, "flags": ["possible_supercell"]}]
                ),
                "user": {"lat": 45.0, "lon": 9.02},
                "alerts_active": [
                    {
                        "id": "a1",
                        "rule_id": "HAIL_RISK",
                        "priority": 2,
                        "title": "x",
                        "message": "x",
                    },
                    {
                        "id": "a2",
                        "rule_id": "LIGHTNING_NEAR",
                        "priority": 1,
                        "title": "y",
                        "message": "y",
                    },
                ],
            },
        },
        {"t": 61_000, "type": "copilot_msg", "payload": {"role": "assistant", "reply": "ok"}},
    ]
    _write(session, events)

    r = build_report(session)
    assert r is not None
    assert r["name"] == "session_x"
    assert r["duration_s"] == 61.0
    assert r["world_frames"] == 2
    assert r["cells_seen"] == 2
    assert r["peak_cells"] == 2
    assert r["max_dbz"] == 61.0 and r["max_dbz_cell"] == 1
    assert r["max_severity"] == 85
    assert r["supercell_cells"] == [1]
    assert r["jump_cells"] == [2]
    assert r["lightning_total"] == 1
    assert r["copilot_replies"] == 1
    assert 1.0 < r["distance_km"] < 2.0
    assert r["nearest_strike_km"] is not None and 1.5 < r["nearest_strike_km"] < 3.0
    assert [a["id"] for a in r["alerts"]] == ["a1", "a2"]
    assert r["alert_counts"] == {"HAIL_RISK": 1, "LIGHTNING_NEAR": 1}


def test_report_reads_a_real_recorder_session(tmp_path):
    rec = SessionRecorder(tmp_path)
    rec.record("world_state", {"cells": _cell_fc([{"id": 5, "max_dbz": 55.0, "severity": 70}])})
    rec.record("source_health", {"noise": True})
    rec.close()

    r = build_report(tmp_path / rec.name)
    assert r is not None
    assert r["world_frames"] == 1
    assert r["max_dbz"] == 55.0
    assert r["max_severity"] == 70
