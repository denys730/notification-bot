"""`heartbeat` — the service's own dependencies are reachable.

Spec: openspec/specs/checkers/heartbeat/spec.md. Its subject is the service, so the audience gates
and deduplication do not apply, and its alerts are SERVICE alerts for the monitoring channel.
"""

from collections.abc import Callable, Mapping, Sequence

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes


class HeartbeatChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.HEARTBEAT

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        """Events are not this checker's input; it probes dependencies instead (see `probe`)."""
        return []

    def probe(self, dependencies: Mapping[str, Callable[[], bool]]) -> AlertEvent | None:
        """Probe each dependency in order and stop at the first failure.

        A later probe cannot be trusted once an earlier dependency is known to be down, and
        repeating the diagnosis adds nothing.
        """
        for name, probe in dependencies.items():
            try:
                healthy = bool(probe())
                detail = "probe returned false"
            except Exception as error:
                healthy = False
                detail = f"{type(error).__name__}: {error}"
            if not healthy:
                return self.alert(
                    entity_id=self.brand,
                    text=f"Heartbeat on {self.brand}: dependency '{name}' is unreachable ({detail})",
                    service_alert=True,
                    dependency=name,
                    detail=detail,
                )
        return None
