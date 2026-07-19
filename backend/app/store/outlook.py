"""Convective outlook store - PRETEMP / ESTOFEX."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_CARTINE_RE = re.compile(r'<img[^>]+src=["\']([^"\']*?/cartine/[^"\']+\.png)["\']', re.IGNORECASE)
_DATED_RE = re.compile(r"/(\d{2}_\d{2}_\d{4})\.png$")


def _https(url: str, base: str = "https://www.pretemp.it") -> str:
    """Absolutise + force https (mixed content is blocked on an https page)."""
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = base + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


def extract_pretemp_maps(html: str) -> tuple[str | None, str | None]:
    """From the PRETEMP homepage, return (today_map_url, tendency_map_url)."""
    urls: list[str] = []
    for m in _CARTINE_RE.finditer(html):
        u = _https(m.group(1))
        if u not in urls:
            urls.append(u)
    if not urls:
        return (None, None)
    today = next(
        (u for u in urls if "tend" not in u.rsplit("/", 1)[-1].lower() and _DATED_RE.search(u)),
        None,
    )
    tend = next((u for u in urls if "tend" in u.rsplit("/", 1)[-1].lower()), None)
    return (today or urls[0], tend)


@dataclass
class Outlook:
    """One convective outlook source, ready for the planning panel."""

    source: str
    title: str
    page_url: str
    attribution: str
    image_url: str | None = None
    tendency_url: str | None = None
    valid: str | None = None
    level: int | None = None
    zones: list[str] | None = None
    summary: str | None = None


class OutlookStore:
    def __init__(self) -> None:
        self._items: list[Outlook] = []
        self._updated_at: datetime | None = None

    def set(self, items: list[Outlook]) -> None:
        self._items = items
        self._updated_at = datetime.now(UTC)

    @property
    def available(self) -> bool:
        return bool(self._items)

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    def wire(self) -> dict:
        return {
            "available": self.available,
            "updated_ms": int(self._updated_at.timestamp() * 1000) if self._updated_at else None,
            "outlooks": [
                {
                    "source": o.source,
                    "title": o.title,
                    "page_url": o.page_url,
                    "attribution": o.attribution,
                    "image_url": o.image_url,
                    "tendency_url": o.tendency_url,
                    "valid": o.valid,
                    "level": o.level,
                    "zones": o.zones,
                    "summary": o.summary,
                }
                for o in self._items
            ],
        }

    def pretemp_level(self) -> dict | None:
        """The current PRETEMP level/zones for the co-pilot snapshot, if extracted."""
        for o in self._items:
            if o.source == "PRETEMP" and o.level is not None:
                return {"level": o.level, "zones": o.zones or []}
        return None


outlook_store = OutlookStore()
