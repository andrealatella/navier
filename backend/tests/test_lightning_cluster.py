"""Lightning clustering + jump tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("sklearn", reason="processing extra not installed")

from app.config import settings  # noqa: E402
from app.models import LightningStrike  # noqa: E402
from app.processing.lightning import LightningAnalyzer  # noqa: E402

T0 = datetime(2026, 7, 12, 15, 0, tzinfo=UTC)


def burst(n: int, lon: float, lat: float, when: datetime, spread: float = 0.02):
    """n strikes packed on a small grid around (lon, lat) at time `when`."""
    return [
        LightningStrike(
            ts=when,
            lon=lon + ((i % 5) - 2) * spread,
            lat=lat + ((i // 5) % 5 - 2) * spread,
        )
        for i in range(n)
    ]


def test_dense_burst_clusters_and_ignores_noise():
    an = LightningAnalyzer(settings)
    strikes = burst(20, 9.0, 45.0, T0)
    strikes += [
        LightningStrike(ts=T0, lon=6.0, lat=44.0),
        LightningStrike(ts=T0, lon=18.0, lat=46.0),
    ]
    clusters = an.analyze(strikes, T0)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.count >= 15
    assert 8.8 < c.centroid[0] < 9.2 and 44.8 < c.centroid[1] < 45.2


def test_cluster_id_is_stable_across_ticks():
    an = LightningAnalyzer(settings)
    c1 = an.analyze(burst(20, 9.0, 45.0, T0), T0)
    c2 = an.analyze(burst(20, 9.01, 45.01, T0 + timedelta(seconds=10)), T0 + timedelta(seconds=10))
    assert c1 and c2 and c1[0].id == c2[0].id


def test_lightning_jump_detected_on_rate_doubling():
    an = LightningAnalyzer(settings)
    for k in range(4):
        t = T0 + timedelta(seconds=10 * k)
        an.analyze(burst(8, 9.0, 45.0, t), t)
    t = T0 + timedelta(seconds=50)
    surge = burst(60, 9.0, 45.0, t)
    clusters = an.analyze(surge, t)
    assert clusters and clusters[0].jump is True


def test_no_jump_without_enough_history():
    an = LightningAnalyzer(settings)
    t = T0
    clusters = an.analyze(burst(60, 9.0, 45.0, t), t)
    assert clusters and clusters[0].jump is False
