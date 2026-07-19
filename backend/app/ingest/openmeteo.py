"""Open-Meteo ingestor for the convective environment."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Iterable

import httpx

from ..config import Settings
from ..store.meteo import MeteoPoint, MeteoStore
from .base import HealthState, Ingestor

logger = logging.getLogger("navier.ingest.openmeteo")

_HOURLY = (
    "cape,wind_speed_500hPa,wind_direction_500hPa,wind_speed_10m,wind_direction_10m,"
    "wind_speed_700hPa,wind_direction_700hPa"
)


def _uv(speed: float, deg: float) -> tuple[float, float]:
    """Meteorological wind (blowing *from* `deg`) → (east, north) vector components."""
    r = math.radians(deg)
    return (-speed * math.sin(r), -speed * math.cos(r))


def shear_ms(
    spd_hi: float | None,
    dir_hi: float | None,
    spd_lo: float | None,
    dir_lo: float | None,
) -> float:
    """0-6 km bulk shear magnitude (m/s): |V(500 hPa) − V(10 m)|."""
    if None in (spd_hi, dir_hi, spd_lo, dir_lo):
        return 0.0
    u_hi, v_hi = _uv(spd_hi, dir_hi)  # type: ignore[arg-type]
    u_lo, v_lo = _uv(spd_lo, dir_lo)  # type: ignore[arg-type]
    return math.hypot(u_hi - u_lo, v_hi - v_lo)


def mean_flow(
    spd_700: float | None,
    dir_700: float | None,
    spd_500: float | None,
    dir_500: float | None,
) -> tuple[float, float] | None:
    """Mean 700-500 hPa steering flow as (speed_ms, bearing_deg the air moves *towards*)."""
    if None in (spd_700, dir_700, spd_500, dir_500):
        return None
    u7, v7 = _uv(spd_700, dir_700)  # type: ignore[arg-type]
    u5, v5 = _uv(spd_500, dir_500)  # type: ignore[arg-type]
    u, v = (u7 + u5) / 2.0, (v7 + v5) / 2.0
    speed = math.hypot(u, v)
    bearing = (math.degrees(math.atan2(u, v)) + 360.0) % 360.0
    return (speed, bearing)


def shear_series(hourly: dict) -> list[float]:
    """Per-hour shear series from a location's `hourly` block."""
    s5 = hourly.get("wind_speed_500hPa", []) or []
    d5 = hourly.get("wind_direction_500hPa", []) or []
    s0 = hourly.get("wind_speed_10m", []) or []
    d0 = hourly.get("wind_direction_10m", []) or []
    n = min(len(s5), len(d5), len(s0), len(d0))
    return [shear_ms(s5[i], d5[i], s0[i], d0[i]) for i in range(n)]


def flow_series(hourly: dict) -> tuple[list[float], list[float]]:
    """Per-hour (speed_ms, bearing_deg) series of the 700-500 hPa mean flow."""
    s7 = hourly.get("wind_speed_700hPa", []) or []
    d7 = hourly.get("wind_direction_700hPa", []) or []
    s5 = hourly.get("wind_speed_500hPa", []) or []
    d5 = hourly.get("wind_direction_500hPa", []) or []
    n = min(len(s7), len(d7), len(s5), len(d5))
    speeds: list[float] = []
    bearings: list[float] = []
    for i in range(n):
        flow = mean_flow(s7[i], d7[i], s5[i], d5[i])
        speeds.append(flow[0] if flow else 0.0)
        bearings.append(flow[1] if flow else 0.0)
    return (speeds, bearings)


def _cape_series(hourly: dict) -> list[float]:
    return [float(x) if x is not None else 0.0 for x in (hourly.get("cape", []) or [])]


def grid_coords(w: float, e: float, s: float, n: float, step: float) -> list[tuple[float, float]]:
    """Regular (lat, lon) lattice covering the bbox, nodes on multiples of `step`."""
    coords: list[tuple[float, float]] = []
    lat = s
    while lat <= n + 1e-9:
        lon = w
        while lon <= e + 1e-9:
            coords.append((round(lat, 3), round(lon, 3)))
            lon += step
        lat += step
    return coords


def _chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class OpenMeteoIngestor(Ingestor):
    name = "openmeteo"

    def __init__(self, store: MeteoStore, settings: Settings) -> None:
        super().__init__()
        self._store = store
        self._s = settings
        self._coords = grid_coords(
            settings.italy_bbox_w,
            settings.italy_bbox_e,
            settings.italy_bbox_s,
            settings.italy_bbox_n,
            settings.meteo_grid_step_deg,
        )

    async def run(self) -> None:
        headers = {"User-Agent": self._s.http_user_agent}
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            while True:
                delay = self._s.meteo_refresh_s
                try:
                    times, points = await self._fetch_grid(client)
                    if points:
                        self._store.set(times, points)
                        self._mark_events(len(points))
                        self._set_state(
                            HealthState.OK, f"{len(points)} punti · {self._s.openmeteo_model}"
                        )
                    else:
                        self._set_state(HealthState.DEGRADED, "nessun punto restituito")
                        delay = self._s.meteo_retry_s
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPStatusError as e:
                    self._set_state(HealthState.DEGRADED, f"HTTP {e.response.status_code}")
                    logger.warning(
                        "openmeteo HTTP %s; retrying in %.0fs",
                        e.response.status_code,
                        self._s.meteo_retry_s,
                    )
                    delay = self._s.meteo_retry_s
                except Exception as e:  # noqa: BLE001
                    self._set_state(HealthState.DEGRADED, f"{type(e).__name__}: {e}")
                    logger.warning("openmeteo fetch error: %s", e)
                    delay = self._s.meteo_retry_s
                await asyncio.sleep(delay)

    async def _fetch_grid(self, client: httpx.AsyncClient) -> tuple[list[str], list[MeteoPoint]]:
        """Fetch the whole grid in URL-length-safe chunks; return (times, points)."""
        times_ref: list[str] = []
        points: list[MeteoPoint] = []
        chunked = list(_chunks(self._coords, self._s.meteo_grid_chunk))
        for ci, chunk in enumerate(chunked):
            if ci > 0:
                await asyncio.sleep(self._s.meteo_chunk_delay_s)
            lats = [c[0] for c in chunk]
            lons = [c[1] for c in chunk]
            params = {
                "latitude": ",".join(str(x) for x in lats),
                "longitude": ",".join(str(x) for x in lons),
                "hourly": _HOURLY,
                "models": self._s.openmeteo_model,
                "wind_speed_unit": "ms",
                "forecast_days": self._s.meteo_forecast_days,
                "timezone": "UTC",
            }
            r = await client.get(self._s.openmeteo_base_url, params=params)
            r.raise_for_status()
            data = r.json()
            locs = data if isinstance(data, list) else [data]
            for (lat, lon), loc in zip(chunk, locs, strict=False):
                hourly = loc.get("hourly") or {}
                if not times_ref and hourly.get("time"):
                    times_ref = list(hourly["time"])
                flow_ms, flow_dir = flow_series(hourly)
                points.append(
                    MeteoPoint(
                        lat=lat,
                        lon=lon,
                        cape=_cape_series(hourly),
                        shear_ms=shear_series(hourly),
                        flow_ms=flow_ms,
                        flow_dir=flow_dir,
                    )
                )
        return times_ref, points
