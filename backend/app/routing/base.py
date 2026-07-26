"""Routing providers behind one interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("navier.routing")

LonLat = tuple[float, float]


@dataclass
class Route:
    """A driving route between two points."""

    provider: str
    distance_km: float
    duration_min: float
    coordinates: list[list[float]]

    def geometry(self) -> dict:
        return {"type": "LineString", "coordinates": self.coordinates}


class RoutingProvider(ABC):
    """A driving-route source. `route()` returns a Route or None (never raises)."""

    name: str = "base"

    @abstractmethod
    async def route(self, start: LonLat, dest: LonLat) -> Route | None:
        """Route from `start` to `dest` (both lon/lat). None if unavailable."""

    async def nearest(self, point: LonLat) -> LonLat | None:
        """Snap `point` onto the drivable road network. None when unsupported."""
        return None
