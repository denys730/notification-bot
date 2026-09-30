"""`status_stuck` — an entity's latest event has sat in a non-final status for too long.

Spec: openspec/specs/checkers/status-stuck/spec.md.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes

DEFAULT_PENDING_STATUSES = ("pending",)
DEFAULT_CACHE_TTL_HOURS = 24.0


class StatusStuckChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.STATUS_STUCK

    REQUIRED_CONFIG_KEYS = frozenset({"pending_minutes"})
    CONFIG_VALUE_BOUNDS = {"pending_minutes": (1, 10080)}
    CONFIG_BOUND_REASONS = {
        "pending_minutes": "Events are kept for 7 days (10080 minutes); an entity cannot be seen stuck for longer.",
    }

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        try:
            pending = float(config.get("pending_minutes", 0))
            ttl_hours = float(config.get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS))
        except (TypeError, ValueError):
            return []
        if ttl_hours * 60 < pending:
            return [
                f"cache_ttl_hours ({ttl_hours:g}) is shorter than pending_minutes ({pending:g}): the same stuck "
                f"entity alerts again on every run until it moves."
            ]
        return []

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        pending = timedelta(minutes=float(self.config["pending_minutes"]))
        statuses = set(self.config.get("pending_statuses") or DEFAULT_PENDING_STATUSES)
        ttl = timedelta(hours=float(self.config.get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS)))

        latest: dict[str, Event] = {}
        for event in events:
            if event.entity_id not in latest or event.last_changed_at >= latest[event.entity_id].last_changed_at:
                latest[event.entity_id] = event

        alerts: list[AlertEvent] = []
        for entity_id, event in sorted(latest.items()):
            if event.status not in statuses:
                continue
            stuck_for = self.now - event.created_at
            if stuck_for <= pending:
                continue
            if not self.audience_check(event):
                continue
            if self.is_entity_recently_notified(entity_id):
                continue
            self.mark_entity_as_notified(entity_id, ttl=ttl)
            minutes = stuck_for.total_seconds() / 60
            alerts.append(
                self.alert(
                    entity_id=entity_id,
                    text=(
                        f"Status stuck on {self.brand}: entity {entity_id} has been '{event.status}' for "
                        f"{minutes:.0f}m (limit {pending.total_seconds() / 60:g}m)"
                    ),
                    status=event.status,
                    stuck_minutes=minutes,
                    pending_minutes=pending.total_seconds() / 60,
                    since=event.created_at.isoformat(),
                )
            )
        return alerts
