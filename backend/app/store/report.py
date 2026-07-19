"""Post-chase session report: turns a recorded session into a summary."""

from __future__ import annotations

import json
from pathlib import Path

from ..processing.geo import haversine_km


def _feature_props(fc: dict) -> list[dict]:
    """Pull the per-cell `properties` out of a cells FeatureCollection payload."""
    return [f.get("properties", {}) for f in (fc.get("features") or []) if isinstance(f, dict)]


def build_report(session_dir: Path) -> dict | None:
    """Summarise one recorded session for the post-chase report, or None if absent."""
    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        return None

    last_t_ms = 0
    world_frames = 0
    lightning_total = 0
    copilot_replies = 0
    peak_cells = 0
    cells_seen: set[int] = set()
    max_dbz = 0.0
    max_dbz_cell: int | None = None
    max_severity = 0
    supercell_ids: set[int] = set()
    jump_ids: set[int] = set()
    radar_ts: set[int] = set()

    prev_user: tuple[float, float] | None = None
    distance_km = 0.0
    current_user: tuple[float, float] | None = None
    nearest_strike_km: float | None = None

    seen_alerts: set[str] = set()
    alerts: list[dict] = []

    with events_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t_ms = int(ev.get("t", 0) or 0)
            last_t_ms = max(last_t_ms, t_ms)
            type_ = ev.get("type")
            payload = ev.get("payload") or {}

            if type_ == "world_state":
                world_frames += 1
                props = _feature_props(payload.get("cells") or {})
                peak_cells = max(peak_cells, len(props))
                for p in props:
                    cid = p.get("id")
                    if isinstance(cid, int):
                        cells_seen.add(cid)
                    dbz = float(p.get("max_dbz") or 0.0)
                    if dbz > max_dbz:
                        max_dbz, max_dbz_cell = dbz, cid if isinstance(cid, int) else None
                    max_severity = max(max_severity, int(p.get("severity") or 0))
                    flags = p.get("flags") or []
                    if "possible_supercell" in flags and isinstance(cid, int):
                        supercell_ids.add(cid)
                    if "lightning_jump" in flags and isinstance(cid, int):
                        jump_ids.add(cid)

                user = payload.get("user")
                if isinstance(user, dict) and user.get("lat") is not None:
                    current_user = (float(user["lon"]), float(user["lat"]))
                    if prev_user is not None:
                        step = haversine_km(prev_user[0], prev_user[1], *current_user)
                        if 0.02 <= step <= 20.0:
                            distance_km += step
                    prev_user = current_user

                for a in payload.get("alerts_active") or []:
                    aid = a.get("id")
                    if not aid or aid in seen_alerts:
                        continue
                    seen_alerts.add(aid)
                    alerts.append(
                        {
                            "id": aid,
                            "rule_id": a.get("rule_id"),
                            "priority": a.get("priority"),
                            "title": a.get("title"),
                            "message": a.get("message"),
                            "t_ms": t_ms,
                        }
                    )

            elif type_ == "lightning_batch":
                strikes = payload.get("strikes") or []
                lightning_total += len(strikes)
                if current_user is not None:
                    for s in strikes:
                        try:
                            d = haversine_km(
                                current_user[0], current_user[1], float(s["lon"]), float(s["lat"])
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                        if nearest_strike_km is None or d < nearest_strike_km:
                            nearest_strike_km = d

            elif type_ == "radar_frames":
                for f in payload.get("frames") or []:
                    ts = f.get("ts")
                    if isinstance(ts, int):
                        radar_ts.add(ts)

            elif type_ == "copilot_msg":
                if payload.get("role") == "assistant":
                    copilot_replies += 1

    alert_counts: dict[str, int] = {}
    for a in alerts:
        rule = a.get("rule_id") or "?"
        alert_counts[rule] = alert_counts.get(rule, 0) + 1

    return {
        "name": session_dir.name,
        "duration_s": round(last_t_ms / 1000.0, 1),
        "world_frames": world_frames,
        "radar_frames": len(radar_ts),
        "distance_km": round(distance_km, 1),
        "lightning_total": lightning_total,
        "nearest_strike_km": round(nearest_strike_km, 1) if nearest_strike_km is not None else None,
        "cells_seen": len(cells_seen),
        "peak_cells": peak_cells,
        "max_dbz": round(max_dbz, 1) if max_dbz else None,
        "max_dbz_cell": max_dbz_cell,
        "max_severity": max_severity,
        "supercell_cells": sorted(supercell_ids),
        "jump_cells": sorted(jump_ids),
        "copilot_replies": copilot_replies,
        "alerts": alerts,
        "alert_counts": alert_counts,
    }
