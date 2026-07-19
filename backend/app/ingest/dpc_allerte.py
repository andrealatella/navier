"""DPC criticality bulletin ingestor for the official alert zones."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from ..config import Settings
from ..store.allerte import AllerteStore
from .base import HealthState, Ingestor

logger = logging.getLogger("navier.ingest.dpc_allerte")

_REPO = "pcm-dpc/DPC-Bollettini-Criticita-Idrogeologica-Idraulica"
_BULLETIN_RE = re.compile(r"files/(\d{8}_\d{4})\.json$")


class DpcAllerteIngestor(Ingestor):
    name = "dpc_allerte"

    def __init__(self, store: AllerteStore, settings: Settings) -> None:
        super().__init__()
        self._store = store
        self._s = settings
        self._last_prefix: str | None = None

    async def run(self) -> None:
        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=40, headers=headers, follow_redirects=True) as client:
            while True:
                delay = self._s.dpc_allerte_refresh_s
                try:
                    prefix = await self._newest_prefix(client)
                    if prefix and prefix != self._last_prefix:
                        n = await self._load_today(client, prefix)
                        self._last_prefix = prefix
                        self._set_state(HealthState.OK, f"{n} zone · {prefix}")
                    elif prefix:
                        self._set_state(HealthState.OK, f"aggiornato · {prefix}")
                    else:
                        self._set_state(HealthState.DEGRADED, "nessun bollettino trovato")
                        delay = self._s.dpc_allerte_retry_s
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                    logger.warning("dpc_allerte error: %s", e)
                    delay = self._s.dpc_allerte_retry_s
                await asyncio.sleep(delay)

    async def _newest_prefix(self, client: httpx.AsyncClient) -> str | None:
        """Newest `YYYYMMDD_HHMM` bulletin prefix via the git trees API (one call)."""
        url = f"https://api.github.com/repos/{_REPO}/git/trees/master?recursive=1"
        r = await client.get(url)
        r.raise_for_status()
        tree = r.json().get("tree", [])
        prefixes = [
            m.group(1) for t in tree if (m := _BULLETIN_RE.match(t.get("path", "")))
        ]
        return max(prefixes) if prefixes else None

    async def _load_today(self, client: httpx.AsyncClient, prefix: str) -> int:
        """Fetch + parse the today FeatureCollection for `prefix`; return zone count."""
        raw = f"https://raw.githubusercontent.com/{_REPO}/master/files/geojson/{prefix}_today.json"
        r = await client.get(raw)
        r.raise_for_status()
        fc = r.json()
        features = fc.get("features", []) if isinstance(fc, dict) else []
        self._store.set(features, issued=prefix)
        self._mark_events(len(features))
        return len(features)
