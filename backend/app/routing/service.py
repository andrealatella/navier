"""Routing provider selection."""

from __future__ import annotations

from ..config import Settings
from .base import RoutingProvider
from .ors import OrsProvider
from .osrm import OsrmProvider


def build_provider(settings: Settings) -> RoutingProvider:
    if settings.ors_api_key:
        return OrsProvider(
            api_key=settings.ors_api_key,
            base_url=settings.ors_base_url,
            user_agent=settings.http_user_agent,
            timeout_s=settings.route_timeout_s,
        )
    return OsrmProvider(
        base_url=settings.osrm_base_url,
        user_agent=settings.http_user_agent,
        timeout_s=settings.route_timeout_s,
    )
