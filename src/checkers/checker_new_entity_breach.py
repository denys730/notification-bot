"""`new_entity_breach` — a new entity's FIRST successful event of one kind reaches a threshold.

Spec: openspec/specs/checkers/new-entity-breach/spec.md. The registration moment comes from the
event stream like everything else a checker reads: the entity's earliest event of
`registration_event_kind`.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes

DEFAULT_REGISTRATION_EVENT_KIND = "registration"
UNKNOWN_ATTRIBUTE = "unknown"


class NewEntityBreachChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.NEW_ENTITY_BREACH

    REQUIRED_CONFIG_KEYS = frozenset({"account_age_hours", "threshold", "event_kind"})
    CONFIG_VALUE_BOUNDS = {"account_age_hours": (1, 168), "threshold": (0, None)}
    CONFIG_BOUND_REASONS = {
        "account_age_hours": "Events are kept for 7 days, so a registration older than that is no longer in the "
        "stream and the entity's age cannot be established.",
        "threshold": "An amount is never negative, so a negative threshold would alert on every first event.",
    }

    @classmethod
    def _registration_kind(cls, config: Mapping[str, Any]) -> str:
        """The kind that marks a registration. A stored null means the same as an absent key."""
        return config.get("registration_event_kind") or DEFAULT_REGISTRATION_EVENT_KIND

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        if not config.get("check_vip_users", True) and not config.get("check_non_vip_users", True):
            warnings.append(
                "check_vip_users and check_non_vip_users are both false: the audience is empty and this rule "
                "alerts about nobody."
            )
        registration_kind = cls._registration_kind(config)
        if config.get("event_kind") == registration_kind:
            warnings.append(
                f"event_kind and registration_event_kind are both '{registration_kind}': the registration is its own "
                f"first qualifying event, so this rule alerts about nobody."
            )
        return warnings

    @staticmethod
    def _earliest_per_entity(events: Sequence[Event], keep: Callable[[Event], bool]) -> dict[str, Event]:
        """The earliest kept event per entity. Events sharing the earliest instant keep the first seen."""
        earliest: dict[str, Event] = {}
        for event in events:
            if not keep(event):
                continue
            if event.entity_id not in earliest or event.created_at < earliest[event.entity_id].created_at:
                earliest[event.entity_id] = event
        return earliest

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        window = timedelta(hours=float(self.config["account_age_hours"]))
        threshold = float(self.config["threshold"])
        kind = self.config["event_kind"]
        registration_kind = self._registration_kind(self.config)

        # An entity's registration is its earliest event of that kind, whatever its status; the entity
        # is new only while that moment is still inside the window ending at this run.
        registrations = {
            entity_id: registration
            for entity_id, registration in self._earliest_per_entity(
                events, lambda event: event.kind == registration_kind
            ).items()
            if self.in_window(registration.created_at, window)
        }

        def qualifies(event: Event) -> bool:
            registration = registrations.get(event.entity_id)
            return (
                registration is not None
                and event.kind == kind
                and event.status == "success"
                and event.created_at >= registration.created_at
            )

        first_qualifying = self._earliest_per_entity(events, qualifies)

        alerts: list[AlertEvent] = []
        for entity_id, event in sorted(first_qualifying.items()):
            if event.amount < threshold:
                continue
            if not self.audience_check(event):
                continue
            if self.is_entity_recently_notified(entity_id):
                continue
            self.mark_entity_as_notified(entity_id, ttl=window)
            registered_at = registrations[entity_id].created_at
            age_hours = (event.created_at - registered_at).total_seconds() / 3600
            alerts.append(
                self.alert(
                    entity_id=entity_id,
                    text=(
                        f"New entity breach on {self.brand}: entity {entity_id} registered at "
                        f"{registered_at.isoformat()} and its first {kind} of {event.amount:,.2f} "
                        f"{event.currency or UNKNOWN_ATTRIBUTE} via {event.source or UNKNOWN_ATTRIBUTE} reached "
                        f"{threshold:,.2f} after {age_hours:.1f}h"
                    ),
                    amount=event.amount,
                    currency=event.currency,
                    source=event.source,
                    threshold=threshold,
                    registered_at=registered_at.isoformat(),
                    occurred_at=event.created_at.isoformat(),
                    age_hours=age_hours,
                    account_age_hours=window.total_seconds() / 3600,
                )
            )
        return alerts
