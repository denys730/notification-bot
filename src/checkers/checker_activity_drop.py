"""`activity_drop` — the brand's event volume in the current window falls below its baseline.

Spec: openspec/specs/checkers/activity-drop/spec.md. A brand-level checker: its entity is the brand,
and the audience gates restrict the COHORT that is counted rather than suppressing a computed alert.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes

DEFAULT_MIN_BASELINE_EVENTS = 20


class ActivityDropChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.ACTIVITY_DROP

    REQUIRED_CONFIG_KEYS = frozenset({"window_minutes", "baseline_days", "drop_percent"})
    CONFIG_VALUE_BOUNDS = {"window_minutes": (5, 1440), "baseline_days": (1, 7), "drop_percent": (1, 100)}
    CONFIG_BOUND_REASONS = {
        "baseline_days": "Events are kept for 7 days, so a longer baseline would average over days that hold nothing.",
    }

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        minimum = config.get("min_baseline_events", DEFAULT_MIN_BASELINE_EVENTS)
        try:
            if float(minimum) < 5:
                return [
                    f"min_baseline_events is {minimum}: a baseline this small reads ordinary quiet minutes as a drop."
                ]
        except (TypeError, ValueError):
            pass
        return []

    def _count(self, events: Sequence[Event], end) -> int:
        window = timedelta(minutes=float(self.config["window_minutes"]))
        return sum(
            1 for event in events if self.audience_check(event) and self.in_window(event.created_at, window, end=end)
        )

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        window = timedelta(minutes=float(self.config["window_minutes"]))
        baseline_days = int(self.config["baseline_days"])
        drop_percent = float(self.config["drop_percent"])
        minimum = float(self.config.get("min_baseline_events", DEFAULT_MIN_BASELINE_EVENTS))

        current = self._count(events, end=self.now)
        baseline_counts = [
            self._count(events, end=self.now - timedelta(days=day)) for day in range(1, baseline_days + 1)
        ]
        baseline = sum(baseline_counts) / len(baseline_counts)
        if baseline < minimum:
            return []

        drop = (1 - current / baseline) * 100
        if drop < drop_percent:
            return []
        if self.is_entity_recently_notified(self.brand):
            return []
        self.mark_entity_as_notified(self.brand, ttl=window)
        minutes = window.total_seconds() / 60
        return [
            self.alert(
                entity_id=self.brand,
                text=(
                    f"Activity drop on {self.brand}: {current} events in the last {minutes:g}m against a baseline "
                    f"of {baseline:.1f} ({drop:.0f}% drop, threshold {drop_percent:g}%)"
                ),
                current=current,
                baseline=baseline,
                drop_percent=drop,
                threshold_percent=drop_percent,
                window_minutes=minutes,
                baseline_days=baseline_days,
            )
        ]
