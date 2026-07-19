"""Alert engine: evaluates the deterministic rules against each WorldState."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..config import Settings
from ..models import Alert
from ..processing.world import WorldState
from .rules import Draft, Rule, default_rules

logger = logging.getLogger("navier.alerts")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _State:
    """Per-rule firing state."""

    active: bool = False
    alert: Alert | None = None
    last_fired: datetime | None = None


class AlertEngine:
    def __init__(self, settings: Settings, rules: list[Rule] | None = None) -> None:
        self._s = settings
        self._rules = rules if rules is not None else default_rules(settings)
        self._state: dict[str, _State] = {r.rule_id: _State() for r in self._rules}
        self._seq = itertools.count(1)

    def evaluate(
        self, ws: WorldState, now: datetime | None = None
    ) -> tuple[list[Alert], list[Alert]]:
        """Return (active_alerts, newly_fired_alerts) for this WorldState."""
        now = now or _now()
        fired: list[Alert] = []

        for rule in self._rules:
            st = self._state[rule.rule_id]
            if st.active:
                draft = rule.still_active(ws)
                if draft is None:
                    st.active = False
                    st.alert = None
                    logger.info("alert cleared: %s", rule.rule_id)
                else:
                    st.alert = self._refresh(st.alert, draft, now)
            else:
                draft = rule.activate(ws)
                if draft is None:
                    continue
                if (
                    st.last_fired is not None
                    and (now - st.last_fired).total_seconds() < self._s.alert_cooldown_s
                ):
                    continue
                alert = self._make(rule, draft, now)
                st.active = True
                st.alert = alert
                st.last_fired = now
                fired.append(alert)
                logger.info("alert fired: %s (P%d)", rule.rule_id, draft.priority)

        active = [s.alert for s in self._state.values() if s.active and s.alert is not None]
        active.sort(key=lambda a: a.priority)
        return active, fired

    def active(self) -> list[Alert]:
        alerts = [s.alert for s in self._state.values() if s.active and s.alert is not None]
        alerts.sort(key=lambda a: a.priority)
        return alerts

    def _make(self, rule: Rule, draft: Draft, now: datetime) -> Alert:
        aid = f"{rule.rule_id}:{next(self._seq)}"
        return Alert(
            id=aid,
            rule_id=rule.rule_id,
            priority=draft.priority,
            title=draft.title,
            message=draft.message,
            tts_text=draft.tts_text,
            geometry=draft.geometry,
            created=now,
            expires=now + timedelta(seconds=self._s.alert_cooldown_s * 2),
        )

    def _refresh(self, prev: Alert | None, draft: Draft, now: datetime) -> Alert:
        """Update an active alert's text in place, preserving id/created (no re-TTS)."""
        if prev is None:
            return self._make_from_draft(draft, now)
        return prev.model_copy(
            update={
                "priority": draft.priority,
                "title": draft.title,
                "message": draft.message,
                "tts_text": draft.tts_text,
                "geometry": draft.geometry,
                "expires": now + timedelta(seconds=self._s.alert_cooldown_s * 2),
            }
        )

    def _make_from_draft(self, draft: Draft, now: datetime) -> Alert:
        return Alert(
            id=f"anon:{next(self._seq)}",
            rule_id="unknown",
            priority=draft.priority,
            title=draft.title,
            message=draft.message,
            tts_text=draft.tts_text,
            geometry=draft.geometry,
            created=now,
        )


def alert_wire(a: Alert) -> dict:
    """Compact alert form for the WS payload."""
    return {
        "id": a.id,
        "rule_id": a.rule_id,
        "priority": a.priority,
        "title": a.title,
        "message": a.message,
        "tts_text": a.tts_text,
        "geometry": a.geometry,
        "created": int(a.created.timestamp() * 1000),
    }


def active_wire(engine: AlertEngine) -> list[dict]:
    return [alert_wire(a) for a in engine.active()]
