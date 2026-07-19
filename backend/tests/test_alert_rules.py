"""Alert engine tests: every rule's activation, hysteresis, cooldown."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.alerts.engine import AlertEngine
from app.alerts.rules import (
    CellInbound,
    CellWeakening,
    DataStale,
    FlashFlood,
    HailRisk,
    LightningJump,
    LightningNear,
    NewStrongCell,
    default_rules,
)
from app.config import settings
from app.models import CellSnapshot, Motion, UserPosition
from app.processing.world import WorldState

T0 = datetime(2026, 7, 12, 15, 0, tzinfo=UTC)
_POLY = {"type": "Polygon", "coordinates": [[[9, 45], [9.1, 45], [9.1, 45.1], [9, 45.1], [9, 45]]]}
USER = UserPosition(lat=45.0, lon=9.0, source="manual")


def cell(
    cid: int = 1,
    *,
    max_dbz: float = 58.0,
    severity: int = 80,
    eta: float | None = None,
    flags: tuple[str, ...] = (),
    centroid: tuple[float, float] = (9.05, 45.05),
    rate: float = 0.0,
    cape: float | None = None,
    poh: float | None = None,
) -> CellSnapshot:
    return CellSnapshot(
        id=cid,
        ts=T0,
        polygon=_POLY,
        centroid=centroid,
        area_km2=120.0,
        max_dbz=max_dbz,
        motion=Motion(speed_kmh=35.0, bearing_deg=90.0),
        severity=severity,
        lightning_rate_min=rate,
        cape=cape,
        poh=poh,
        trend="steady",
        forecast_cones=[],
        eta_user_min=eta,
        flags=list(flags),
    )


def one(rule) -> AlertEngine:
    return AlertEngine(settings, [rule])


def test_lightning_near_fires_p1_within_radius():
    eng = one(LightningNear(settings))
    active, fired = eng.evaluate(WorldState(ts=T0, user=USER, nearest_strike_km=3.0), T0)
    assert len(fired) == 1 and fired[0].priority == 1
    assert fired[0].rule_id == "LIGHTNING_NEAR"
    assert active[0].tts_text


def test_lightning_near_hysteresis_holds_in_the_band():
    eng = one(LightningNear(settings))
    eng.evaluate(WorldState(ts=T0, user=USER, nearest_strike_km=3.0), T0)
    active, fired = eng.evaluate(
        WorldState(ts=T0, user=USER, nearest_strike_km=6.0), T0 + timedelta(seconds=15)
    )
    assert not fired and len(active) == 1
    active, _ = eng.evaluate(
        WorldState(ts=T0, user=USER, nearest_strike_km=9.0), T0 + timedelta(seconds=30)
    )
    assert active == []


def test_lightning_near_cooldown_blocks_immediate_refire():
    eng = one(LightningNear(settings))
    eng.evaluate(WorldState(ts=T0, user=USER, nearest_strike_km=3.0), T0)
    eng.evaluate(
        WorldState(ts=T0, user=USER, nearest_strike_km=20.0), T0 + timedelta(seconds=5)
    )
    _, fired = eng.evaluate(
        WorldState(ts=T0, user=USER, nearest_strike_km=2.0), T0 + timedelta(seconds=30)
    )
    assert not fired
    later = T0 + timedelta(seconds=settings.alert_cooldown_s + 31)
    _, fired = eng.evaluate(WorldState(ts=later, user=USER, nearest_strike_km=2.0), later)
    assert len(fired) == 1


def test_cell_inbound_fires_and_has_hysteresis():
    eng = one(CellInbound(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(3, severity=70, eta=10.0)])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 1 and "3" in fired[0].title

    ws2 = WorldState(ts=T0, user=USER, cells=[cell(3, severity=45, eta=18.0)])
    active, fired = eng.evaluate(ws2, T0 + timedelta(seconds=15))
    assert not fired and len(active) == 1
    ws3 = WorldState(ts=T0, user=USER, cells=[cell(3, severity=30, eta=10.0)])
    active, _ = eng.evaluate(ws3, T0 + timedelta(seconds=30))
    assert active == []


def test_cell_inbound_needs_user_inside_cone():
    eng = one(CellInbound(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(3, severity=90, eta=None)])
    _, fired = eng.evaluate(ws, T0)
    assert not fired


def test_hail_risk_escalates_to_p1_with_jump():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(2, max_dbz=62, flags=("lightning_jump",))])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 1


def test_hail_risk_p2_between_thresholds():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(2, max_dbz=56, flags=("lightning_jump",))])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 2


def test_hail_risk_needs_confirmation():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(2, max_dbz=62)])
    _, fired = eng.evaluate(ws, T0)
    assert not fired
    ws2 = WorldState(ts=T0, user=USER, cells=[cell(2, max_dbz=62)], cape=1800)
    _, fired = eng.evaluate(ws2, T0)
    assert len(fired) == 1


def test_hail_risk_confirmed_by_per_cell_cape():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, user=USER, cape=200, cells=[cell(2, max_dbz=62, cape=2000)])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1


def test_hail_risk_confirmed_by_poh():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(2, max_dbz=62, poh=0.75)])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1
    assert "POH 75%" in fired[0].message
    ws2 = WorldState(ts=T0, user=USER, cells=[cell(3, max_dbz=62, poh=0.4)])
    _, fired = one(HailRisk(settings)).evaluate(ws2, T0)
    assert not fired


def test_hail_risk_out_of_range_is_ignored():
    eng = one(HailRisk(settings))
    far = cell(2, max_dbz=62, flags=("lightning_jump",), centroid=(12.5, 45.0))
    ws = WorldState(ts=T0, user=USER, cells=[far])
    _, fired = eng.evaluate(ws, T0)
    assert not fired


def test_hail_risk_silent_without_position():
    eng = one(HailRisk(settings))
    ws = WorldState(ts=T0, cells=[cell(2, max_dbz=62, flags=("lightning_jump",))])
    _, fired = eng.evaluate(ws, T0)
    assert not fired


def test_flash_flood_on_sri_or_official_alert():
    eng = one(FlashFlood(settings))
    _, fired = eng.evaluate(WorldState(ts=T0, user=USER, local_sri_mmh=35.0), T0)
    assert len(fired) == 1 and fired[0].priority == 1

    eng2 = one(FlashFlood(settings))
    _, fired = eng2.evaluate(WorldState(ts=T0, user=USER, dpc_alert_level="arancione"), T0)
    assert len(fired) == 1

    eng3 = one(FlashFlood(settings))
    _, fired = eng3.evaluate(WorldState(ts=T0, user=USER), T0)
    assert not fired


def test_lightning_jump_alert():
    eng = one(LightningJump(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(4, flags=("lightning_jump",))])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 2


def test_data_stale_on_old_radar_or_lightning():
    eng = one(DataStale(settings))
    _, fired = eng.evaluate(WorldState(ts=T0, radar_age_s=1000.0), T0)
    assert len(fired) == 1 and fired[0].priority == 2

    eng2 = one(DataStale(settings))
    _, fired = eng2.evaluate(WorldState(ts=T0, lightning_age_s=200.0), T0)
    assert len(fired) == 1


def test_new_strong_cell_announced_once_per_cell():
    eng = one(NewStrongCell(settings))
    ws = WorldState(ts=T0, user=USER, cells=[cell(7, severity=65)])
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 3
    active, fired = eng.evaluate(ws, T0 + timedelta(seconds=15))
    assert not fired


def test_cell_weakening_needs_target_and_drop():
    eng = one(CellWeakening(settings))
    ws = WorldState(
        ts=T0,
        cells=[cell(9, severity=40)],
        target_cell_id=9,
        target_severity_drop=0.4,
    )
    _, fired = eng.evaluate(ws, T0)
    assert len(fired) == 1 and fired[0].priority == 3

    eng2 = one(CellWeakening(settings))
    ws2 = WorldState(ts=T0, cells=[cell(9)], target_cell_id=9, target_severity_drop=0.1)
    _, fired = eng2.evaluate(ws2, T0)
    assert not fired


def test_engine_sorts_active_alerts_by_priority():
    eng = AlertEngine(settings, default_rules(settings))
    ws = WorldState(
        ts=T0,
        user=USER,
        nearest_strike_km=3.0,
        radar_age_s=1000.0,
        cells=[cell(5, severity=65)],
    )
    active, fired = eng.evaluate(ws, T0)
    priorities = [a.priority for a in active]
    assert priorities == sorted(priorities)
    assert priorities[0] == 1
    assert {a.rule_id for a in fired} >= {"LIGHTNING_NEAR", "DATA_STALE", "NEW_STRONG_CELL"}
