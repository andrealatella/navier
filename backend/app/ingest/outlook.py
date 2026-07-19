"""Convective-outlook ingestor: PRETEMP and ESTOFEX."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from ..config import Settings
from ..store.outlook import Outlook, OutlookStore, extract_pretemp_maps
from .base import HealthState, Ingestor

logger = logging.getLogger("navier.ingest.outlook")

OutlookAnalyzer = Callable[[bytes, str], Awaitable[dict | None]]


class OutlookIngestor(Ingestor):
    name = "outlook"

    def __init__(
        self,
        store: OutlookStore,
        settings: Settings,
        analyzer: OutlookAnalyzer | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._s = settings
        self._analyzer = analyzer
        self._analyzed_url: str | None = None

    async def run(self) -> None:
        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            while True:
                delay = self._s.outlook_refresh_s
                try:
                    items = await self._build(client)
                    self._store.set(items)
                    self._mark_events(len(items))
                    have_map = any(o.image_url for o in items)
                    self._set_state(
                        HealthState.OK,
                        "PRETEMP+ESTOFEX" if have_map else "solo link (mappa non trovata)",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                    logger.warning("outlook scrape error: %s", e)
                    delay = self._s.outlook_retry_s
                await asyncio.sleep(delay)

    async def _build(self, client: httpx.AsyncClient) -> list[Outlook]:
        items: list[Outlook] = []

        pretemp = Outlook(
            source="PRETEMP",
            title="Previsione temporali (Italia)",
            page_url="https://www.pretemp.it",
            attribution="PRETEMP - pretemp.it",
        )
        try:
            r = await client.get("https://www.pretemp.it")
            r.raise_for_status()
            today, tend = extract_pretemp_maps(r.text)
            pretemp.image_url = today
            pretemp.tendency_url = tend
            if today:
                await self._analyze(client, pretemp, today)
        except Exception as e:  # noqa: BLE001
            logger.warning("PRETEMP scrape failed: %s", e)
        items.append(pretemp)

        items.append(
            Outlook(
                source="ESTOFEX",
                title="European Storm Forecast (ESTOFEX)",
                page_url="https://www.estofex.org",
                attribution="ESTOFEX - estofex.org",
            )
        )
        return items

    async def _analyze(self, client: httpx.AsyncClient, pretemp: Outlook, image_url: str) -> None:
        """Vision-read the day's PRETEMP map into a level/zones once per new map."""
        if self._analyzer is None or image_url == self._analyzed_url:
            return
        try:
            img = await client.get(image_url)
            img.raise_for_status()
            mime = img.headers.get("content-type", "image/png").split(";")[0].strip()
            result = await self._analyzer(img.content, mime or "image/png")
        except Exception as e:  # noqa: BLE001
            logger.warning("PRETEMP vision analysis failed: %s", e)
            return
        self._analyzed_url = image_url
        if result is not None:
            pretemp.level = result.get("level")
            pretemp.zones = result.get("zones") or []
            pretemp.summary = result.get("summary") or None
            logger.info("PRETEMP outlook: level %s, zones %s", pretemp.level, pretemp.zones)
