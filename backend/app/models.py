"""Typed event models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class LightningStrike(BaseModel):
    """A single detected lightning strike."""

    ts: datetime
    lat: float
    lon: float
    src: str = "blitzortung"


class UserPosition(BaseModel):
    """User GPS position. Source: phone companion, gpsd, or manual click."""

    ts: datetime = Field(default_factory=utcnow)
    lat: float
    lon: float
    speed_kmh: float | None = None
    heading_deg: float | None = None
    source: Literal["phone", "gpsd", "manual"] = "manual"


class Motion(BaseModel):
    """A cell's estimated movement vector."""

    speed_kmh: float
    bearing_deg: float


class CellSnapshot(BaseModel):
    """One tracked storm cell at a given time."""

    id: int
    ts: datetime
    polygon: dict[str, Any]
    centroid: tuple[float, float]
    area_km2: float
    max_dbz: float
    motion: Motion | None = None
    severity: int = 0
    lightning_rate_min: float = 0.0
    cape: float | None = None
    poh: float | None = None
    motion_deviation_deg: float | None = None
    trend: Literal["up", "steady", "down"] = "steady"
    forecast_cones: list[dict[str, Any]] = Field(default_factory=list)
    eta_user_min: float | None = None
    flags: list[str] = Field(default_factory=list)
    sev_series: list[int] = Field(default_factory=list)


class LightningCluster(BaseModel):
    """A DBSCAN cluster of recent strikes."""

    id: int
    centroid: tuple[float, float]
    count: int
    rate_min: float
    jump: bool = False


class Alert(BaseModel):
    """Deterministic alert emitted by the alert engine. Never by the LLM."""

    id: str
    rule_id: str
    priority: Literal[1, 2, 3]
    title: str
    message: str
    tts_text: str
    geometry: dict[str, Any] | None = None
    created: datetime = Field(default_factory=utcnow)
    expires: datetime | None = None




class WSMessage(BaseModel):
    """Generic tagged message used both ways on the live socket."""

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RouteRequest(BaseModel):
    """Body of `POST /api/route`."""

    cell_id: int | None = None
    mode: Literal["intercept", "direct"] = "intercept"
    dest_lat: float | None = None
    dest_lon: float | None = None
    start_lat: float | None = None
    start_lon: float | None = None
