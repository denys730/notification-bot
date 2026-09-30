"""first_event_breach — one test per scenario of openspec/specs/checkers/first-event-breach/spec.md."""

from datetime import UTC, datetime, timedelta

from checkers import FirstEventBreachChecker, Suppression
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(**config):
    base = {"threshold": 1000, "max_entity_age_hours": 24, "event_kind": "inflow"}
    base.update(config)
    return {"brand": "DEMO", "checker_name": "FEB", "config": base}


def event(entity: str, amount: float, hours_ago: float, status: str = "success", **kw) -> Event:
    return Event(
        entity_id=entity, kind="inflow", created_at=NOW - timedelta(hours=hours_ago), amount=amount, status=status, **kw
    )


def registration(entity: str, hours_ago: float, **kw) -> Event:
    return Event(entity_id=entity, kind="registration", created_at=NOW - timedelta(hours=hours_ago), **kw)


def test_first_successful_event_at_the_threshold_alerts() -> None:
    events = [registration("10007", 8), event("10007", 1000, 6)]
    alerts = FirstEventBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["10007"]
    assert alerts[0].brand == "DEMO" and "1,000.00" in alerts[0].text
    assert alerts[0].context["amount"] == 1000 and alerts[0].context["entity_age_hours"] == 2


def test_first_successful_event_below_the_threshold_is_silent() -> None:
    events = [registration("10007", 8), event("10007", 999, 6), event("10007", 5000, 2)]
    assert FirstEventBreachChecker(row(), now=NOW).check(events) == []


def test_an_earlier_unsuccessful_event_does_not_take_the_place_of_the_first() -> None:
    events = [
        registration("10007", 8),
        event("10007", 200, 7, status="failed"),
        event("10007", 300, 7, status="pending"),
        event("10007", 2000, 6),
    ]
    alerts = FirstEventBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["10007"] and alerts[0].context["amount"] == 2000


def test_events_of_another_kind_are_ignored() -> None:
    events = [
        registration("10007", 8),
        Event(entity_id="10007", kind="session", created_at=NOW - timedelta(hours=7)),
        Event(entity_id="10007", kind="outflow", created_at=NOW - timedelta(hours=7), amount=9000),
        event("10007", 2000, 6),
    ]
    assert len(FirstEventBreachChecker(row(), now=NOW).check(events)) == 1
    assert FirstEventBreachChecker(row(event_kind="outflow"), now=NOW).check(events)[0].context["amount"] == 9000


def test_audience_gates_apply_to_the_first_event() -> None:
    gated = {**row(check_vip_users=False), "segments": ["Business__34"], "regions": ["eu"]}
    checker = FirstEventBreachChecker(gated, now=NOW)
    profile = {"region": "EU", "segments": ("Business__34",)}
    assert checker.check([registration("10007", 8), event("10007", 2000, 6, is_vip=True, **profile)]) == []
    assert (
        checker.check([registration("10007", 8), event("10007", 2000, 6, region="LATAM", segments=("Business__34",))])
        == []
    )
    assert (
        checker.check([registration("10007", 8), event("10007", 2000, 6, region="EU", segments=("Business__33",))])
        == []
    )
    assert len(checker.check([registration("10007", 8), event("10007", 2000, 6, **profile)])) == 1


def test_entity_registered_inside_the_age_limit_alerts() -> None:
    events = [registration("10007", 30), event("10007", 2000, 7)]
    alerts = FirstEventBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["10007"] and alerts[0].context["entity_age_hours"] == 23


def test_entity_exactly_at_the_age_limit_is_silent() -> None:
    events = [registration("10007", 30), event("10007", 2000, 6)]
    assert FirstEventBreachChecker(row(), now=NOW).check(events) == []


def test_entity_older_than_the_age_limit_is_silent() -> None:
    events = [registration("10007", 200), event("10007", 2000, 6)]
    assert FirstEventBreachChecker(row(), now=NOW).check(events) == []


def test_entity_without_a_registration_event_is_silent() -> None:
    assert FirstEventBreachChecker(row(), now=NOW).check([event("10007", 2000, 6)]) == []


def test_registration_kind_is_configurable() -> None:
    events = [Event(entity_id="10007", kind="signup", created_at=NOW - timedelta(hours=8)), event("10007", 2000, 6)]
    assert FirstEventBreachChecker(row(), now=NOW).check(events) == []
    assert len(FirstEventBreachChecker(row(registration_kind="signup"), now=NOW).check(events)) == 1


def test_event_predating_the_registration_is_silent() -> None:
    events = [registration("10007", 6), event("10007", 2000, 8)]
    assert FirstEventBreachChecker(row(), now=NOW).check(events) == []


def test_age_is_measured_at_the_event_not_at_the_run() -> None:
    events = [registration("10007", 200), event("10007", 2000, 198)]
    later = FirstEventBreachChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in later] == ["10007"] and later[0].context["entity_age_hours"] == 2


def test_alert_carries_its_evidence() -> None:
    events = [registration("10007", 8), event("10007", 1200, 6)]
    alert = FirstEventBreachChecker(row(), now=NOW).check(events)[0]
    assert {
        "amount",
        "threshold",
        "event_kind",
        "entity_age_hours",
        "max_entity_age_hours",
        "registered_at",
        "event_at",
    } <= set(alert.context)
    assert alert.context["registered_at"] == (NOW - timedelta(hours=8)).isoformat()
    assert alert.context["event_at"] == (NOW - timedelta(hours=6)).isoformat()
    assert "10007" in alert.text and "2h after registration" in alert.text
    assert f"registration at {(NOW - timedelta(hours=8)).isoformat()}" in alert.text


def test_currency_and_payment_method_are_quoted_when_present() -> None:
    events = [registration("10007", 8), event("10007", 1200, 6, currency="EUR", payment_method="visa")]
    alert = FirstEventBreachChecker(row(), now=NOW).check(events)[0]
    assert alert.context["currency"] == "EUR" and alert.context["payment_method"] == "visa"
    assert "1,200.00 EUR" in alert.text and "visa" in alert.text


def test_alert_without_a_currency_omits_it() -> None:
    events = [registration("10007", 8), event("10007", 1200, 6)]
    alert = FirstEventBreachChecker(row(), now=NOW).check(events)[0]
    assert "currency" not in alert.context and "payment_method" not in alert.context
    assert "1,200.00 " in alert.text and "None" not in alert.text and "via" not in alert.text


def test_suppression_lasts_the_ttl() -> None:
    suppression = Suppression()
    events = [registration("10007", 8), event("10007", 2000, 6)]
    first = FirstEventBreachChecker(row(cache_ttl_hours=1), now=NOW, suppression=suppression).check(events)
    assert len(first) == 1
    assert suppression.keys() == ["DEMO:first_event_breach:10007"]
    inside = FirstEventBreachChecker(row(cache_ttl_hours=1), now=NOW + timedelta(minutes=30), suppression=suppression)
    assert inside.check(events) == []
    after = FirstEventBreachChecker(row(cache_ttl_hours=1), now=NOW + timedelta(minutes=61), suppression=suppression)
    assert len(after.check(events)) == 1


def test_config_hooks() -> None:
    assert FirstEventBreachChecker.REQUIRED_CONFIG_KEYS == {"threshold", "max_entity_age_hours", "event_kind"}
    assert FirstEventBreachChecker.CONFIG_VALUE_BOUNDS["max_entity_age_hours"] == (1, 168)
    assert FirstEventBreachChecker.CONFIG_VALUE_BOUNDS["threshold"] == (0, None)
    assert FirstEventBreachChecker.config_warnings({"check_vip_users": False, "check_non_vip_users": False})
    assert FirstEventBreachChecker.config_warnings({"event_kind": "registration", "registration_kind": "registration"})
    assert FirstEventBreachChecker.config_warnings({"max_entity_age_hours": 24, "cache_ttl_hours": 1})
    assert FirstEventBreachChecker.config_warnings({"max_entity_age_hours": "x", "cache_ttl_hours": 1}) == []
    assert FirstEventBreachChecker.config_warnings({}) == []
