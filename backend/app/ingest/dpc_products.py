"""DPC auxiliary products ingestor: POH and SRI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from ..config import Settings
from .base import HealthState, Ingestor

logger = logging.getLogger("navier.ingest.dpc_products")

ProductSink = Callable[[object], Awaitable[None]]


class DpcProductsIngestor(Ingestor):
    name = "dpc_products"

    def __init__(self, poh_sink: ProductSink, sri_sink: ProductSink, settings: Settings) -> None:
        super().__init__()
        self._sinks = {"POH": poh_sink, "SRI": sri_sink}
        self._s = settings
        self._last_ts: dict[str, int] = {}
        self._decode = None

    async def run(self) -> None:
        try:
            from ..processing.dpc_grid import decode_product
        except Exception as e:  # noqa: BLE001
            self._set_state(
                HealthState.DEGRADED,
                "modulo processing assente: 'pip install -e \".[processing]\"'",
            )
            logger.warning("dpc_products disabled: %s (POH/SRI rules stay dormant)", e)
            await asyncio.Event().wait()
            return
        self._decode = decode_product

        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            while True:
                fetched = 0
                for product in ("POH", "SRI"):
                    try:
                        if await self._fetch_one(client, product):
                            fetched += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        logger.warning("dpc_products %s error: %s", product, e)
                if self._last_ts:
                    self._set_state(HealthState.OK, "POH/SRI · " + ", ".join(sorted(self._last_ts)))
                else:
                    self._set_state(HealthState.DEGRADED, "nessun prodotto")
                await asyncio.sleep(self._s.radar_poll_s)

    async def _fetch_one(self, client: httpx.AsyncClient, product: str) -> bool:
        """Fetch+decode the newest frame of one product; feed its sink. True if new."""
        r = await client.get(
            f"{self._s.dpc_api_base}/findLastProductByType", params={"type": product}
        )
        r.raise_for_status()
        products = r.json().get("lastProducts") or []
        if not products:
            return False
        ts_ms = int(products[0]["time"])
        if self._last_ts.get(product) == ts_ms:
            return False

        r2 = await client.post(
            f"{self._s.dpc_api_base}/downloadProduct",
            json={"productType": product, "productDate": ts_ms},
        )
        r2.raise_for_status()
        url = r2.json().get("url")
        if not url:
            return False
        tif = (await client.get(url)).content
        grid = await asyncio.to_thread(self._decode, tif, ts_ms)
        self._last_ts[product] = ts_ms
        self._mark_events(1)
        await self._sinks[product](grid)
        return True
