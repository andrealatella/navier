"""Budget manager: daily cap, Pacific-day reset, 429 backoff, proactive spacing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.copilot.budget import Budget, pacific_day


def _t(h: int, m: int = 0, d: int = 13) -> datetime:
    return datetime(2026, 7, d, h, m, tzinfo=UTC)


def test_daily_limit_blocks_after_cap():
    b = Budget(daily_limit=3)
    now = _t(12)
    for _ in range(3):
        assert b.allow(now)[0]
        b.record_call(now)
    ok, reason = b.allow(now)
    assert not ok and reason == "daily_limit"
    assert b.status(now)["quota_exhausted"] is True


def test_counter_resets_on_pacific_day_change():
    b = Budget(daily_limit=5)
    now = _t(12)
    for _ in range(5):
        b.record_call(now)
    assert not b.allow(now)[0]
    nxt = _t(9, d=14)
    assert b.allow(nxt)[0]
    assert b.status(nxt)["calls_today"] == 0


def test_429_backoff_then_recovers():
    b = Budget(daily_limit=100)
    now = _t(12)
    b.record_quota_error(now, retry_after_s=60)
    ok, reason = b.allow(now + timedelta(seconds=30))
    assert not ok and reason == "quota"
    assert b.status(now + timedelta(seconds=30))["resumes_in_s"] is not None
    assert b.allow(now + timedelta(seconds=61))[0]


def test_429_default_backoff_when_no_retry_after():
    b = Budget(daily_limit=100, default_backoff_s=300)
    now = _t(12)
    b.record_quota_error(now, retry_after_s=None)
    assert not b.allow(now + timedelta(seconds=299))[0]
    assert b.allow(now + timedelta(seconds=301))[0]


def test_proactive_spacing():
    b = Budget(daily_limit=100, min_interval_s=45)
    now = _t(12)
    assert b.proactive_ready(now)
    b.record_call(now)
    assert not b.proactive_ready(now + timedelta(seconds=20))
    assert b.proactive_ready(now + timedelta(seconds=45))


def test_proactive_blocked_by_quota():
    b = Budget(daily_limit=100, min_interval_s=1)
    now = _t(12)
    b.record_quota_error(now, retry_after_s=120)
    assert not b.proactive_ready(now + timedelta(seconds=60))


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "budget.json"
    now = _t(12)
    b1 = Budget(daily_limit=10, state_path=path)
    b1.record_call(now)
    b1.record_call(now)
    b2 = Budget(daily_limit=10, state_path=path)
    assert b2.status(now)["calls_today"] == 2


def test_pacific_day_is_utc_minus_8():
    assert pacific_day(_t(3, d=13)) == "2026-07-12"
    assert pacific_day(_t(9, d=13)) == "2026-07-13"
