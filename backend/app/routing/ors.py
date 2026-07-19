"""OpenRouteService routing provider."""

from __future__ import annotations

import logging

import httpx

from .base import LonLat, Route, RoutingProvider

logger = logging.getLogger("navier.routing.ors")


class OrsProvider(RoutingProvider):
    name = "ors"

    def __init__(self, api_key: str, base_url: str, user_agent: str, timeout_s: float) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._ua = user_agent
        self._timeout = timeout_s

    async def route(self, start: LonLat, dest: LonLat) -> Route | None:
        url = f"{self._base}/v2/directions/driving-car/geojson"
        body = {"coordinates": [[start[0], start[1]], [dest[0], dest[1]]]}
        headers = {
            "Authorization": self._key,
            "Content-Type": "application/json",
            "User-Agent": self._ua,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("ORS route failed: %s", e)
            return None

        feats = data.get("features") or []
        if not feats:
            logger.warning("ORS returned no route")
            return None
        feat = feats[0]
        geom = feat.get("geometry", {})
        summary = (feat.get("properties", {}) or {}).get("summary", {}) or {}
        if geom.get("type") != "LineString" or not geom.get("coordinates"):
            return None
        return Route(
            provider=self.name,
            distance_km=round(summary.get("distance", 0.0) / 1000.0, 2),
            duration_min=round(summary.get("duration", 0.0) / 60.0, 1),
            coordinates=[[float(lon), float(lat)] for lon, lat in geom["coordinates"]],
        )
