"""OSRM routing provider."""

from __future__ import annotations

import logging

import httpx

from .base import LonLat, Route, RoutingProvider

logger = logging.getLogger("navier.routing.osrm")


class OsrmProvider(RoutingProvider):
    name = "osrm"

    def __init__(self, base_url: str, user_agent: str, timeout_s: float) -> None:
        self._base = base_url.rstrip("/")
        self._ua = user_agent
        self._timeout = timeout_s

    async def route(self, start: LonLat, dest: LonLat) -> Route | None:
        coords = f"{start[0]:.6f},{start[1]:.6f};{dest[0]:.6f},{dest[1]:.6f}"
        url = f"{self._base}/route/v1/driving/{coords}"
        params = {"overview": "full", "geometries": "geojson", "steps": "false"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, params=params, headers={"User-Agent": self._ua})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("OSRM route failed: %s", e)
            return None

        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning("OSRM returned no route: %s", data.get("code"))
            return None
        rt = data["routes"][0]
        geom = rt.get("geometry", {})
        if geom.get("type") != "LineString" or not geom.get("coordinates"):
            return None
        return Route(
            provider=self.name,
            distance_km=round(rt["distance"] / 1000.0, 2),
            duration_min=round(rt["duration"] / 60.0, 1),
            coordinates=[[float(lon), float(lat)] for lon, lat in geom["coordinates"]],
        )

    async def nearest(self, point: LonLat) -> LonLat | None:
        url = f"{self._base}/nearest/v1/driving/{point[0]:.6f},{point[1]:.6f}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, params={"number": 1}, headers={"User-Agent": self._ua})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("OSRM nearest failed: %s", e)
            return None

        if data.get("code") != "Ok":
            return None
        waypoints = data.get("waypoints") or []
        if not waypoints:
            return None
        loc = waypoints[0].get("location") or []
        if len(loc) < 2:
            return None
        return (float(loc[0]), float(loc[1]))
