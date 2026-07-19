"""Convective-outlook parser tests."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.ingest.outlook import OutlookIngestor
from app.store.outlook import Outlook, OutlookStore, extract_pretemp_maps

_HTML = """
<img src="//pretemp.altervista.org/alterpages/logopretemp.png">
<img src="https://pretemp.altervista.org/archivio/2026/luglio/cartine/14_07_2026.png">
<img src="https://www.pretemp.it/archivio/2026/luglio/cartine/tend_15_07_2026.png">
<img src="http://pretemp.altervista.org/archivio/2026/luglio/cartine/tend2_17_07_2026.png">
<img src="https://www.pretemp.it/varie/banner_stormrep.png">
"""


def test_extract_today_and_tendency():
    today, tend = extract_pretemp_maps(_HTML)
    assert today == "https://pretemp.altervista.org/archivio/2026/luglio/cartine/14_07_2026.png"
    assert tend == "https://www.pretemp.it/archivio/2026/luglio/cartine/tend_15_07_2026.png"


def test_extract_forces_https():
    html = '<img src="http://pretemp.altervista.org/archivio/2026/luglio/cartine/14_07_2026.png">'
    today, _ = extract_pretemp_maps(html)
    assert today is not None and today.startswith("https://")


def test_extract_none_when_no_map():
    today, tend = extract_pretemp_maps("<html><img src='/logo.png'></html>")
    assert today is None and tend is None


def test_store_wire():
    from app.store.outlook import Outlook

    store = OutlookStore()
    assert store.wire()["available"] is False
    store.set(
        [
            Outlook(
                source="PRETEMP",
                title="t",
                page_url="https://www.pretemp.it",
                attribution="PRETEMP",
                image_url="https://x/y.png",
            )
        ]
    )
    w = store.wire()
    assert w["available"] is True
    assert w["outlooks"][0]["image_url"] == "https://x/y.png"


def test_store_carries_vision_level():
    store = OutlookStore()
    store.set(
        [
            Outlook(
                source="PRETEMP",
                title="t",
                page_url="https://www.pretemp.it",
                attribution="PRETEMP",
                image_url="https://x/y.png",
                level=2,
                zones=["Piemonte", "Lombardia"],
                summary="Temporali forti al Nord-Ovest.",
            )
        ]
    )
    w = store.wire()["outlooks"][0]
    assert w["level"] == 2 and w["zones"] == ["Piemonte", "Lombardia"]
    assert store.pretemp_level() == {"level": 2, "zones": ["Piemonte", "Lombardia"]}


def test_store_pretemp_level_none_until_extracted():
    store = OutlookStore()
    store.set([Outlook(source="PRETEMP", title="t", page_url="p", attribution="a")])
    assert store.pretemp_level() is None


class _FakeResponse:
    def __init__(self, content=b"", content_type="image/png"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None


class _FakeClient:
    """Minimal async httpx stand-in: records image GETs, returns a fixed image."""

    def __init__(self):
        self.gets = []

    async def get(self, url):
        self.gets.append(url)
        return _FakeResponse(b"\x89PNG-bytes")


def test_ingestor_vision_analyses_once_per_map():
    calls = []

    async def analyzer(data, mime):
        calls.append((data, mime))
        return {"level": 3, "zones": ["Veneto"], "summary": "Forte."}

    ing = OutlookIngestor(OutlookStore(), settings, analyzer=analyzer)
    client = _FakeClient()
    pretemp = Outlook(source="PRETEMP", title="t", page_url="p", attribution="a")

    async def drive():
        url = "https://x/cartine/19_07_2026.png"
        await ing._analyze(client, pretemp, url)
        await ing._analyze(client, pretemp, url)

    asyncio.run(drive())
    assert len(calls) == 1
    assert pretemp.level == 3 and pretemp.zones == ["Veneto"]
    assert pretemp.summary == "Forte."


def test_ingestor_vision_no_analyzer_is_noop():
    ing = OutlookIngestor(OutlookStore(), settings, analyzer=None)
    pretemp = Outlook(source="PRETEMP", title="t", page_url="p", attribution="a")

    asyncio.run(ing._analyze(_FakeClient(), pretemp, "https://x/m.png"))
    assert pretemp.level is None
