"""Call budget for the Gemini co-pilot."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("navier.copilot.budget")

_PACIFIC_OFFSET = timedelta(hours=8)


def pacific_day(now: datetime) -> str:
    """The calendar day at UTC-8, ISO string - our daily-quota bucket key."""
    return (now.astimezone(UTC) - _PACIFIC_OFFSET).date().isoformat()


class Budget:
    def __init__(
        self,
        daily_limit: int,
        *,
        min_interval_s: float = 45.0,
        default_backoff_s: float = 300.0,
        state_path: Path | None = None,
    ) -> None:
        self._daily_limit = daily_limit
        self._min_interval_s = min_interval_s
        self._default_backoff_s = default_backoff_s
        self._state_path = state_path
        self._day: str = ""
        self._count = 0
        self._quota_until: datetime | None = None
        self._last_call: datetime | None = None
        self._load()

    def allow(self, now: datetime) -> tuple[bool, str]:
        """Whether any call may be made now: (ok, reason-if-not)."""
        self._roll_day(now)
        if self._quota_until is not None and now < self._quota_until:
            return False, "quota"
        if self._count >= self._daily_limit:
            return False, "daily_limit"
        return True, ""

    def proactive_ready(self, now: datetime, min_interval_s: float | None = None) -> bool:
        """Whether a *proactive* call is due: budget ok AND spacing elapsed."""
        ok, _ = self.allow(now)
        if not ok:
            return False
        gap = min_interval_s if min_interval_s is not None else self._min_interval_s
        if self._last_call is None:
            return True
        return (now - self._last_call).total_seconds() >= gap

    def record_call(self, now: datetime) -> None:
        """Count one successful (billed) call and remember when it happened."""
        self._roll_day(now)
        self._count += 1
        self._last_call = now
        self._save()

    def record_quota_error(self, now: datetime, retry_after_s: float | None = None) -> None:
        """An HTTP 429: back off until retry-after (or the default) elapses."""
        self._roll_day(now)
        backoff = retry_after_s if retry_after_s and retry_after_s > 0 else self._default_backoff_s
        self._quota_until = now + timedelta(seconds=backoff)
        logger.warning("copilot quota hit; resting %.0fs", backoff)

    def status(self, now: datetime) -> dict:
        self._roll_day(now)
        resting = self._quota_until is not None and now < self._quota_until
        exhausted = resting or self._count >= self._daily_limit
        resumes_in = (
            int((self._quota_until - now).total_seconds())
            if resting and self._quota_until
            else None
        )
        return {
            "calls_today": self._count,
            "daily_limit": self._daily_limit,
            "quota_exhausted": exhausted,
            "resumes_in_s": resumes_in,
        }

    def _roll_day(self, now: datetime) -> None:
        today = pacific_day(now)
        if today != self._day:
            if self._day:
                logger.info("copilot daily counter reset (%s -> %s)", self._day, today)
            self._day = today
            self._count = 0
            self._quota_until = None
            self._save()

    def _load(self) -> None:
        if self._state_path is None:
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._day = str(data.get("day", ""))
        self._count = int(data.get("count", 0))

    def _save(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"day": self._day, "count": self._count}), encoding="utf-8"
            )
        except OSError as e:
            logger.debug("copilot budget save failed: %s", e)
