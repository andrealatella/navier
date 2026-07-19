"""DPC criticality store tests."""

from __future__ import annotations

from app.store.allerte import AllerteStore, parse_level


def test_parse_level():
    assert parse_level("Ordinaria / ALLERTA GIALLA") == "giallo"
    assert parse_level("Moderata / ALLERTA ARANCIONE") == "arancione"
    assert parse_level("Elevata / ALLERTA ROSSA") == "rosso"
    assert parse_level("Assenza di fenomeni significativi / NESSUNA ALLERTA") == "verde"
    assert parse_level(None) == "verde"


def _square(cx: float, cy: float, d: float = 0.5) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [cx - d, cy - d],
                [cx + d, cy - d],
                [cx + d, cy + d],
                [cx - d, cy + d],
                [cx - d, cy - d],
            ]
        ],
    }


def _feature(cx, cy, *, idro="verde", idrau="verde", temp="verde", shown=None):
    lv = {
        "verde": "NESSUNA ALLERTA",
        "giallo": "ALLERTA GIALLA",
        "arancione": "ALLERTA ARANCIONE",
        "rosso": "ALLERTA ROSSA",
    }
    shown = shown or max(
        (idro, idrau, temp), key=lambda x: ["verde", "giallo", "arancione", "rosso"].index(x)
    )
    return {
        "type": "Feature",
        "geometry": _square(cx, cy),
        "properties": {
            "Nome zona": f"zona {cx},{cy}",
            "Rappresentata nella mappa": lv[shown],
            "Per rischio idrogeologico": lv[idro],
            "Per rischio idraulico": lv[idrau],
            "Per rischio temporali": lv[temp],
            "Comuni": ["A", "B", "C"],
        },
    }


def test_level_at_finds_hydro_zone():
    store = AllerteStore()
    store.set([_feature(9, 45, idro="arancione"), _feature(12, 42, temp="giallo")], "20260714_1546")
    assert store.level_at(9.0, 45.0) == "arancione"
    assert store.level_at(12.0, 42.0) is None
    assert store.level_at(0.0, 0.0) is None


def test_wire_only_alerted_zones_and_drops_comuni():
    store = AllerteStore()
    store.set(
        [
            _feature(9, 45, idro="giallo"),
            _feature(1, 1),
            _feature(12, 42, temp="arancione"),
        ],
        "20260714_1546",
    )
    wire = store.wire()
    feats = wire["zones"]["features"]
    assert len(feats) == 2
    assert wire["available"] is True and wire["issued"] == "20260714_1546"
    for f in feats:
        assert "Comuni" not in f["properties"]
        assert f["properties"]["level"] in {"giallo", "arancione", "rosso"}


def test_empty_store():
    store = AllerteStore()
    assert store.available is False
    assert store.level_at(9, 45) is None
    assert store.wire()["available"] is False
