"""`first_event_breach` — an entity's first successful event of a kind reaches a threshold while the entity is new.

Spec: openspec/specs/checkers/first-event-breach/spec.md.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from checkers.base import AlertEvent, BaseChecker, Event
from constants import CheckerCodes

DEFAULT_REGISTRATION_KIND = "registration"
DEFAULT_CACHE_TTL_HOURS = 24.0


class FirstEventBreachChecker(BaseChecker):
    CHECKER_CODE = CheckerCodes.FIRST_EVENT_BREACH

    REQUIRED_CONFIG_KEYS = frozenset({"threshold", "max_entity_age_hours", "event_kind"})
    CONFIG_VALUE_BOUNDS = {"threshold": (0, None), "max_entity_age_hours": (1, 168)}
    CONFIG_BOUND_REASONS = {
        "max_entity_age_hours": (
            "Events are kept for 7 days, so beyond that the registration event is no longer in the stream and the "
            "entity's age cannot be established."
        ),
    }

    @classmethod
    def config_warnings(cls, config: Mapping[str, Any]) -> list[str]:
        warnings: list[str] = []
        if not config.get("check_vip_users", True) and not config.get("check_non_vip_users", True):
            warnings.append(
                "check_vip_users and check_non_vip_users are both false: the audience is empty and this rule "
                "alerts about nobody."
            )
        registration_kind = str(config.get("registration_kind", DEFAULT_REGISTRATION_KIND))
        if config.get("event_kind") and str(config["event_kind"]) == registration_kind:
            warnings.append(
                f"event_kind and registration_kind are both '{registration_kind}': the registration event is itself "
                f"the first watched event, so this rule fires on registration."
            )
        try:
            max_age_hours = float(config["max_entity_age_hours"])
            ttl_hours = float(config.get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS))
        except (KeyError, TypeError, ValueError):
            return warnings
        if ttl_hours < max_age_hours:
            warnings.append(
                f"cache_ttl_hours ({ttl_hours:g}) is shorter than max_entity_age_hours ({max_age_hours:g}): the same "
                f"first event alerts again while the entity is still inside the age limit."
            )
        return warnings

    def check(self, events: Sequence[Event]) -> list[AlertEvent]:
        threshold = float(self.config["threshold"])
        max_age_hours = float(self.config["max_entity_age_hours"])
        max_age = timedelta(hours=max_age_hours)
        kind = str(self.config["event_kind"])
        registration_kind = str(self.config.get("registration_kind", DEFAULT_REGISTRATION_KIND))
        ttl = timedelta(hours=float(self.config.get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS)))

        registered_at: dict[str, datetime] = {}
        first_event: dict[str, Event] = {}
        for event in events:
            if event.kind == registration_kind:
                current = registered_at.get(event.entity_id)
                if current is None or event.created_at < current:
                    registered_at[event.entity_id] = event.created_at
            if event.kind == kind and event.status == "success":
                earliest = first_event.get(event.entity_id)
                if earliest is None or event.created_at < earliest.created_at:
                    first_event[event.entity_id] = event

        alerts: list[AlertEvent] = []
        for entity_id, event in sorted(first_event.items()):
            registration = registered_at.get(entity_id)
            if registration is None:
                continue
            age = event.created_at - registration
            # A negative age is an event that predates the registration it would be measured against —
            # not a first event *after* registration, whatever a clock skew or a backfill says.
            if not timedelta(0) <= age < max_age:
                continue
            if event.amount < threshold:
                continue
            if not self.audience_check(event):
                continue
            if self.is_entity_recently_notified(entity_id):
                continue
            self.mark_entity_as_notified(entity_id, ttl=ttl)
            age_hours = age.total_seconds() / 3600
            amount_text = f"{event.amount:,.2f}" + (f" {event.currency}" if event.currency else "")
            via = f" via {event.payment_method}" if event.payment_method else ""
            descriptive = {
                key: value
                for key, value in (("currency", event.currency), ("payment_method", event.payment_method))
                if value
            }
            alerts.append(
                self.alert(
                    entity_id=entity_id,
                    text=(
                        f"First event breach on {self.brand}: entity {entity_id} reached {amount_text}{via} on its "
                        f"first successful {kind} {age_hours:g}h after registration at {registration.isoformat()} "
                        f"(threshold {threshold:,.2f}, limit {max_age_hours:g}h)"
                    ),
                    amount=event.amount,
                    threshold=threshold,
                    event_kind=kind,
                    entity_age_hours=age_hours,
                    max_entity_age_hours=max_age_hours,
                    registered_at=registration.isoformat(),
                    event_at=event.created_at.isoformat(),
                    **descriptive,
                )
            )
        return alerts
