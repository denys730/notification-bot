"""The contract every demo checker inherits.

A checker is a pure function of a configuration row, a clock and a list of events: `check(events)`
returns the alert events it would raise. Nothing schedules it and nothing delivers what it returns.
That is what keeps this a demo — the shape is a production one (per-row config, audience gates,
deduplication by entity, config validation hooks), the pipeline behind it is not there.

Documented in `openspec/specs/event-checking/spec.md`; each checker's own behaviour in
`openspec/specs/checkers/<code>/spec.md`. Read those before changing anything here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from constants import CheckerCodes


@dataclass(frozen=True)
class Event:
    """One thing that happened to one entity. The only input a checker reads.

    Abstract on purpose: `kind` and `status` are free strings, `amount` is a number in a single
    unit. A real system would map deposits, bets or logins onto this shape.
    """

    entity_id: str
    kind: str
    created_at: datetime
    amount: float = 0.0
    status: str = "success"
    updated_at: datetime | None = None
    is_vip: bool = False
    region: str | None = None
    # `{segmentation_id}__{value}` entries the entity currently belongs to.
    segments: tuple[str, ...] = ()

    @property
    def last_changed_at(self) -> datetime:
        return self.updated_at or self.created_at


@dataclass
class AlertEvent:
    """One decision by a checker that something needs announcing."""

    checker_code: str
    brand: str
    entity_id: str
    text: str
    context: dict[str, Any] = field(default_factory=dict)
    # A service alert is about the alerting system itself and goes to the monitoring channel.
    service_alert: bool = False


class Suppression:
    """In-memory replacement for a Redis deduplication cache.

    Keys are `{brand}:{checker_code}:{entity_id}` — the format a deployed cache would use — so a test
    can assert on exactly what a deployment would key on.
    """

    def __init__(self) -> None:
        self._until: dict[str, datetime] = {}

    def is_suppressed(self, key: str, now: datetime) -> bool:
        until = self._until.get(key)
        return until is not None and now < until

    def mark(self, key: str, now: datetime, ttl: timedelta) -> None:
        self._until[key] = now + ttl

    def keys(self) -> list[str]:
        return sorted(self._until)


class BaseChecker:
    """Lifecycle and gates shared by every checker. Subclasses implement `check()` only."""

    CHECKER_CODE: ClassVar[CheckerCodes]

    # Config validation hooks, all empty by default. A knob listed in REQUIRED_CONFIG_KEYS is one
    # the checker reads without a fallback; a bounded knob must also be a required one.
    REQUIRED_CONFIG_KEYS: ClassVar[frozenset[str]] = frozenset()
    CONFIG_VALUE_BOUNDS: ClassVar[dict[str, tuple[float | None, float | None]]] = {}
    CONFIG_BOUND_REASONS: ClassVar[dict[str, str]] = {}

    def __init__(
        self,
        row: Mapping[str, Any],
        *,
        now: datetime | None = None,
        suppression: Suppression | None = None,
    ) -> None:
        self.row = dict(row)
        self.brand = str(row.get("brand") or "").upper()
        self.checker_name = str(row.get("checker_name") or "")
        self.config: dict[str, Any] = dict(row.get("config") or {})
        self.now = now or datetime.now(UTC)
        self.suppression = suppression or Suppression()

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        """Advice about a legal-but-surprising configuration. Never raises, never rejects."""
        return []

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        raise NotImplementedError

    # ---- audience gates -------------------------------------------------------------------------

    def vip_config_check(self, event: Event) -> bool:
        """`check_vip_users` / `check_non_vip_users` inside `config`; an unset flag counts as true."""
        wants_vip = bool(self.config.get("check_vip_users", True))
        wants_non_vip = bool(self.config.get("check_non_vip_users", True))
        return wants_vip if event.is_vip else wants_non_vip

    def segment_config_check(self, event: Event) -> bool:
        """Row-level `segments` allow list of `{segmentation_id}__{value}`; unset or empty = no restriction."""
        wanted = self.row.get("segments") or []
        if not wanted:
            return True
        return any(entry in event.segments for entry in wanted)

    def region_config_check(self, event: Event) -> bool:
        """Row-level `regions` allow list, matched case-insensitively; unset or empty = no restriction."""
        wanted = [str(region).strip().upper() for region in (self.row.get("regions") or []) if str(region).strip()]
        if not wanted:
            return True
        return (event.region or "").strip().upper() in wanted

    def audience_check(self, event: Event) -> bool:
        return self.vip_config_check(event) and self.segment_config_check(event) and self.region_config_check(event)

    # ---- deduplication --------------------------------------------------------------------------

    @property
    def key_prefix(self) -> str:
        return f"{self.brand}:{self.CHECKER_CODE.value}"

    def suppression_key(self, entity_id: str) -> str:
        return f"{self.key_prefix}:{entity_id}"

    def is_entity_recently_notified(self, entity_id: str) -> bool:
        return self.suppression.is_suppressed(self.suppression_key(entity_id), self.now)

    def mark_entity_as_notified(self, entity_id: str, ttl: timedelta) -> None:
        self.suppression.mark(self.suppression_key(entity_id), self.now, ttl)

    # ---- helpers --------------------------------------------------------------------------------

    def in_window(self, moment: datetime, window: timedelta, *, end: datetime | None = None) -> bool:
        """Inclusive membership of `moment` in the window ending at `end` (the run's clock by default)."""
        end = end or self.now
        return end - window <= moment <= end

    def alert(self, entity_id: str, text: str, *, service_alert: bool = False, **context: Any) -> AlertEvent:
        return AlertEvent(
            checker_code=self.CHECKER_CODE.value,
            brand=self.brand,
            entity_id=entity_id,
            text=text,
            context=context,
            service_alert=service_alert,
        )
