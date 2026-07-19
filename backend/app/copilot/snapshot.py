"""Snapshot builder."""

from __future__ import annotations

from ..processing.geo import bearing_deg, compass_it, haversine_km
from ..processing.world import WorldState

MAX_CELLS = 6


def _round(x: float | None, ndigits: int = 0) -> float | None:
    if x is None:
        return None
    r = round(x, ndigits)
    return int(r) if ndigits == 0 else r


def build_snapshot(
    ws: WorldState,
    *,
    target_cell_id: int | None = None,
    route_eta_min: float | None = None,
    intercept_ok: bool | None = None,
    alerts_active: list[dict] | None = None,
    outlook: dict | None = None,
) -> dict:
    """Build the compact copilot snapshot from a fused WorldState."""
    user = ws.user
    snap: dict = {"t": ws.ts.isoformat(timespec="seconds")}

    if user is not None:
        snap["user"] = {
            "lat": round(user.lat, 4),
            "lon": round(user.lon, 4),
            "speed_kmh": _round(user.speed_kmh),
            "heading": _round(user.heading_deg),
            "moving": bool(user.speed_kmh and user.speed_kmh > 3),
        }

    meteo = {}
    if ws.cape is not None:
        meteo["cape"] = _round(ws.cape)
    if ws.shear_ms is not None:
        meteo["shear_0_6km_ms"] = _round(ws.shear_ms)
    if ws.local_sri_mmh is not None:
        meteo["sri_mmh"] = _round(ws.local_sri_mmh)
    if ws.dpc_alert_level is not None:
        meteo["allerta_dpc"] = ws.dpc_alert_level
    if meteo:
        snap["meteo_local"] = meteo

    cells = sorted(ws.cells, key=lambda c: c.severity, reverse=True)[:MAX_CELLS]
    rows = []
    for c in cells:
        row: dict = {
            "id": c.id,
            "max_dbz": _round(c.max_dbz),
            "trend": c.trend,
            "lightning_min": _round(c.lightning_rate_min),
            "severity": c.severity,
            "eta_user_min": _round(c.eta_user_min),
        }
        if user is not None:
            lon, lat = c.centroid
            row["dist_km"] = _round(haversine_km(user.lon, user.lat, lon, lat))
            row["bearing"] = compass_it(bearing_deg(user.lon, user.lat, lon, lat))
        if c.motion is not None:
            row["motion"] = {
                "kmh": _round(c.motion.speed_kmh),
                "verso": compass_it(c.motion.bearing_deg),
            }
        if c.flags:
            row["flags"] = c.flags
        if c.motion_deviation_deg is not None:
            row["deviazione_flusso_deg"] = _round(c.motion_deviation_deg)
        rows.append(row)
    snap["cells"] = rows

    if alerts_active:
        snap["alerts_active"] = [_alert_tag(a) for a in alerts_active]

    if outlook and outlook.get("level") is not None:
        snap["outlook_pretemp"] = {"level": outlook["level"], "zone": outlook.get("zones") or []}

    if target_cell_id is not None:
        snap["target"] = {
            "cell_id": target_cell_id,
            "route_eta_min": _round(route_eta_min),
            "intercept_ok": intercept_ok,
        }

    snap["data_age_s"] = {
        "radar": _round(ws.radar_age_s),
        "lightning": _round(ws.lightning_age_s),
    }
    return snap


def _alert_tag(a: dict) -> str:
    """A short human tag like 'HAIL_RISK (P1)' for the active-alerts list."""
    rule = a.get("rule_id", "?")
    prio = a.get("priority")
    return f"{rule} (P{prio})" if prio else str(rule)
