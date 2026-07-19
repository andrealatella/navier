"""Decoder tests against 12 real Blitzortung messages recorded 2026-07-12."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.ingest.blitzortung import BlitzortungIngestor, decode

FIXTURE = Path(__file__).parent / "fixtures" / "blitzortung_raw_sample.txt"


def _raw_messages() -> list[str]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln.strip()]


def test_fixture_present() -> None:
    msgs = _raw_messages()
    assert len(msgs) == 12


@pytest.mark.parametrize("raw", _raw_messages())
def test_decode_yields_valid_strike_json(raw: str) -> None:
    obj = json.loads(decode(raw))
    assert isinstance(obj["time"], int)
    assert -90 <= float(obj["lat"]) <= 90
    assert -180 <= float(obj["lon"]) <= 180
    assert 1_600_000_000 < obj["time"] / 1e9 < 2_000_000_000


def test_decode_empty_is_safe() -> None:
    assert decode("") == ""


def test_parse_filters_to_italy_bbox() -> None:
    ing = BlitzortungIngestor(sink=_noop_sink, settings=Settings())
    total = sum(len(ing._parse(raw)) for raw in _raw_messages())
    assert total == 0


def test_parse_keeps_a_strike_inside_italy() -> None:
    ing = BlitzortungIngestor(sink=_noop_sink, settings=Settings())
    fake = json.dumps({"time": 1_783_870_323_000_000_000, "lat": 44.9, "lon": 8.2})
    strikes = ing._parse(fake)
    assert len(strikes) == 1
    assert strikes[0].src == "blitzortung"
    assert 44.0 < strikes[0].lat < 45.5


async def _noop_sink(_strikes) -> None:  # pragma: no cover - test stub
    return None
