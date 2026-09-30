"""`threshold_breach` — an entity's successful amounts, summed over a rolling window, reach a threshold.

Spec: openspec/specs/checkers/threshold-breach/spec.md.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes


class ThresholdBreachChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.THRESHOLD_BREACH

    REQUIRED_CONFIG_KEYS = frozenset({"monitoring_window_hours", "threshold"})
    CONFIG_VALUE_BOUNDS = {"monitoring_window_hours": (1, 168), "threshold": (0, None)}
    CONFIG_BOUND_REASONS = {
        "monitoring_window_hours": "Events are kept for 7 days, so a longer window would sum over data that is no longer there.",
    }

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        if not config.get("check_vip_users", True) and not config.get("check_non_vip_users", True):
            warnings.append(
                "check_vip_users and check_non_vip_users are both false: the audience is empty and this rule "
                "alerts about nobody."
            )
        return warnings

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        window = timedelta(hours=float(self.config["monitoring_window_hours"]))
        threshold = float(self.config["threshold"])
        kind = self.config.get("event_kind")

        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        latest: dict[str, Event] = {}
        for event in events:
            if event.status != "success":
                continue
            if kind and event.kind != kind:
                continue
            if not self.in_window(event.created_at, window):
                continue
            totals[event.entity_id] = totals.get(event.entity_id, 0.0) + event.amount
            counts[event.entity_id] = counts.get(event.entity_id, 0) + 1
            if event.entity_id not in latest or event.created_at >= latest[event.entity_id].created_at:
                latest[event.entity_id] = event

        alerts: list[AlertEvent] = []
        for entity_id, total in sorted(totals.items()):
            if total < threshold:
                continue
            if not self.audience_check(latest[entity_id]):
                continue
            if self.is_entity_recently_notified(entity_id):
                continue
            self.mark_entity_as_notified(entity_id, ttl=window)
            hours = window.total_seconds() / 3600
            alerts.append(
                self.alert(
                    entity_id=entity_id,
                    text=(
                        f"Threshold breach on {self.brand}: entity {entity_id} reached {total:,.2f} "
                        f"over {hours:g}h (threshold {threshold:,.2f}, {counts[entity_id]} events)"
                    ),
                    total=total,
                    threshold=threshold,
                    window_hours=hours,
                    events=counts[entity_id],
                    window_start=(self.now - window).isoformat(),
                    window_end=self.now.isoformat(),
                )
            )
        return alerts
