"""new_entity_breach — one test per scenario of openspec/specs/checkers/new-entity-breach/spec.md."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from api.admin.checkers import validate_checker_config
from checkers import NewEntityBreachChecker, Suppression
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(**config):
    base = {"account_age_hours": 24, "threshold": 1000, "event_kind": "inflow"}
    base.update(config)
    return {"brand": "demo", "checker_name": "NEB", "config": base}


def registered(entity: str, hours_ago: float, kind: str = "registration", **kw) -> Event:
    return Event(entity_id=entity, kind=kind, created_at=NOW - timedelta(hours=hours_ago), **kw)


def event(entity: str, amount: float, hours_ago: float, status: str = "success", kind: str = "inflow", **kw) -> Event:
    return Event(
        entity_id=entity, kind=kind, created_at=NOW - timedelta(hours=hours_ago), amount=amount, status=status, **kw
    )


def test_entity_registered_inside_the_window_is_judged() -> None:
    events = [registered("10006", 23.5), event("10006", 1500, 23)]
    alerts = NewEntityBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["10006"]


def test_registration_before_the_window_is_silent() -> None:
    events = [registered("10006", 25), event("10006", 1500, 1)]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []


def test_entity_without_a_registration_event_is_silent() -> None:
    assert NewEntityBreachChecker(row(), now=NOW).check([event("10006", 1500, 1)]) == []


def test_first_amount_at_or_above_the_threshold_alerts() -> None:
    events = [registered("10006", 2), event("10006", 1000, 1)]
    alerts = NewEntityBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["10006"]
    assert alerts[0].context["amount"] == 1000 and alerts[0].brand == "DEMO"


def test_first_amount_below_the_threshold_is_not_revived_by_a_later_one() -> None:
    events = [registered("10006", 2), event("10006", 500, 1.5), event("10006", 5000, 1)]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []


def test_unsuccessful_events_never_qualify_as_first() -> None:
    events = [
        registered("10006", 3),
        event("10006", 5000, 2.5, status="failed"),
        event("10006", 5000, 2, status="pending"),
        event("10006", 1200, 1),
    ]
    alerts = NewEntityBreachChecker(row(), now=NOW).check(events)
    assert [a.context["amount"] for a in alerts] == [1200]


def test_events_of_another_kind_take_no_part() -> None:
    events = [registered("10006", 2), event("10006", 5000, 1.5, kind="outflow"), event("10006", 500, 1)]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []


def test_events_before_the_registration_moment_are_not_first() -> None:
    events = [registered("10006", 2), event("10006", 500, 3), event("10006", 1500, 1)]
    alerts = NewEntityBreachChecker(row(), now=NOW).check(events)
    assert [a.context["amount"] for a in alerts] == [1500]
    only_before = [registered("10007", 2), event("10007", 5000, 3)]
    assert NewEntityBreachChecker(row(), now=NOW).check(only_before) == []


def test_alert_carries_its_evidence() -> None:
    events = [registered("10006", 3), event("10006", 1500, 1, currency="EUR", source="card")]
    alert = NewEntityBreachChecker(row(), now=NOW).check(events)[0]
    assert {
        "amount",
        "currency",
        "source",
        "threshold",
        "registered_at",
        "occurred_at",
        "age_hours",
        "account_age_hours",
    } <= set(alert.context)
    assert alert.context["registered_at"] == (NOW - timedelta(hours=3)).isoformat()
    assert alert.context["occurred_at"] == (NOW - timedelta(hours=1)).isoformat()
    assert alert.context["age_hours"] == 2 and alert.context["account_age_hours"] == 24
    assert "10006" in alert.text and "1,500.00 EUR" in alert.text and "card" in alert.text


def test_attributes_the_event_does_not_carry_read_as_unknown() -> None:
    events = [registered("10006", 3), event("10006", 1500, 1)]
    alert = NewEntityBreachChecker(row(), now=NOW).check(events)[0]
    assert alert.context["currency"] is None and alert.context["source"] is None
    assert "1,500.00 unknown" in alert.text and "via unknown" in alert.text


def test_vip_gate_uses_the_first_qualifying_event() -> None:
    checker = NewEntityBreachChecker(row(check_vip_users=False), now=NOW)
    assert checker.check([registered("10006", 2), event("10006", 1500, 1, is_vip=True)]) == []
    assert len(checker.check([registered("10007", 2), event("10007", 1500, 1, is_vip=False)])) == 1


def test_segment_and_region_gates() -> None:
    gated = {**row(), "segments": ["Business__34"], "regions": ["eu"]}
    checker = NewEntityBreachChecker(gated, now=NOW)
    wrong_segment = [registered("10006", 2), event("10006", 1500, 1, region="EU", segments=("Business__33",))]
    wrong_region = [registered("10006", 2), event("10006", 1500, 1, region="LATAM", segments=("Business__34",))]
    allowed = [registered("10006", 2), event("10006", 1500, 1, region="EU", segments=("Business__34",))]
    assert checker.check(wrong_segment) == []
    assert checker.check(wrong_region) == []
    assert len(checker.check(allowed)) == 1


def test_suppression_lasts_one_account_age_window() -> None:
    suppression = Suppression()
    events = [registered("10006", 2), event("10006", 1500, 1)]
    first = NewEntityBreachChecker(row(), now=NOW, suppression=suppression).check(events)
    assert len(first) == 1
    assert suppression.keys() == ["DEMO:new_entity_breach:10006"]
    later = NOW + timedelta(hours=23)
    still_new = [
        Event(entity_id="10006", kind="registration", created_at=later - timedelta(hours=2)),
        Event(entity_id="10006", kind="inflow", created_at=later - timedelta(hours=1), amount=2500),
    ]
    assert NewEntityBreachChecker(row(), now=later, suppression=suppression).check(still_new) == []


def test_registration_event_kind_is_configurable() -> None:
    events = [registered("10006", 2, kind="signup"), event("10006", 1500, 1)]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []
    assert len(NewEntityBreachChecker(row(registration_event_kind="signup"), now=NOW).check(events)) == 1


def test_the_registration_is_the_earliest_event_of_its_kind_whatever_its_status() -> None:
    events = [
        registered("10006", 30, status="failed"),
        registered("10006", 2),
        event("10006", 1500, 1),
    ]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []


def test_events_sharing_the_earliest_instant_keep_the_first_in_the_stream() -> None:
    events = [registered("10006", 2), event("10006", 500, 1), event("10006", 5000, 1)]
    assert NewEntityBreachChecker(row(), now=NOW).check(events) == []


def test_config_hooks() -> None:
    assert NewEntityBreachChecker.REQUIRED_CONFIG_KEYS == {"account_age_hours", "threshold", "event_kind"}
    assert NewEntityBreachChecker.CONFIG_VALUE_BOUNDS["account_age_hours"] == (1, 168)
    assert NewEntityBreachChecker.CONFIG_VALUE_BOUNDS["threshold"] == (0, None)
    assert NewEntityBreachChecker.CONFIG_BOUND_REASONS["account_age_hours"]
    assert NewEntityBreachChecker.config_warnings({"check_vip_users": False, "check_non_vip_users": False})
    assert NewEntityBreachChecker.config_warnings({"event_kind": "inflow", "registration_event_kind": "inflow"})
    same_kind_by_default = {"event_kind": "registration", "registration_event_kind": None}
    assert NewEntityBreachChecker.config_warnings(same_kind_by_default)
    assert NewEntityBreachChecker.config_warnings({}) == []


def test_an_account_age_window_longer_than_retention_is_rejected() -> None:
    config = {"account_age_hours": 500, "threshold": 1000, "event_kind": "inflow"}
    with pytest.raises(HTTPException) as rejected:
        validate_checker_config("new_entity_breach", config)
    message = rejected.value.detail["details"]["config"][0]
    assert "1 to 168" in message and "7 days" in message
    validate_checker_config("new_entity_breach", {**config, "account_age_hours": 24})
