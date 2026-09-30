"""The checker registry. Every checker is listed here exactly once, or the admin API cannot validate its config."""

from checkers.base import AlertEvent, BaseChecker, Event, Suppression
from checkers.checker_activity_drop import ActivityDropChecker
from checkers.checker_heartbeat import HeartbeatChecker
from checkers.checker_status_stuck import StatusStuckChecker
from checkers.checker_threshold_breach import ThresholdBreachChecker

ALL_CHECKERS: list[type[BaseChecker]] = [
    HeartbeatChecker,
    ThresholdBreachChecker,
    ActivityDropChecker,
    StatusStuckChecker,
]


def checker_for_code(checker_code: str | None) -> type[BaseChecker] | None:
    """The registered checker class claiming this code, or None for a code nothing claims."""
    if not checker_code:
        return None
    value = getattr(checker_code, "value", checker_code)
    for checker_cls in ALL_CHECKERS:
        if checker_cls.CHECKER_CODE.value == value:
            return checker_cls
    return None


__all__ = [
    "ALL_CHECKERS",
    "ActivityDropChecker",
    "AlertEvent",
    "BaseChecker",
    "Event",
    "HeartbeatChecker",
    "StatusStuckChecker",
    "Suppression",
    "ThresholdBreachChecker",
    "checker_for_code",
]
