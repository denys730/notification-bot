"""threshold_breach — one test per scenario of openspec/specs/checkers/threshold-breach/spec.md."""

from datetime import UTC, datetime, timedelta

from checkers import Suppression, ThresholdBreachChecker
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(**config):
    base = {"monitoring_window_hours": 24, "threshold": 5000}
    base.update(config)
    return {"brand": "demo", "checker_name": "TB", "config": base}


def event(entity: str, amount: float, hours_ago: float, status: str = "success", **kw) -> Event:
    return Event(
        entity_id=entity, kind="inflow", created_at=NOW - timedelta(hours=hours_ago), amount=amount, status=status, **kw
    )


def test_amounts_at_or_above_the_threshold_alert() -> None:
    alerts = ThresholdBreachChecker(row(), now=NOW).check([event("10001", 3000, 1), event("10001", 2000, 5)])
    assert [a.entity_id for a in alerts] == ["10001"]
    assert alerts[0].context["total"] == 5000 and alerts[0].context["events"] == 2
    assert alerts[0].brand == "DEMO" and "5,000.00" in alerts[0].text
    assert {"total", "threshold", "window_hours", "events", "window_start", "window_end"} <= set(alerts[0].context)


def test_unsuccessful_events_do_not_count() -> None:
    events = [
        event("10001", 3000, 1),
        event("10001", 3000, 2, status="failed"),
        event("10001", 3000, 3, status="pending"),
    ]
    assert ThresholdBreachChecker(row(), now=NOW).check(events) == []


def test_events_outside_the_window_are_excluded() -> None:
    events = [event("10001", 3000, 1), event("10001", 3000, 25)]
    assert ThresholdBreachChecker(row(), now=NOW).check(events) == []


def test_total_below_the_threshold_is_silent() -> None:
    assert ThresholdBreachChecker(row(), now=NOW).check([event("10001", 4999, 1)]) == []


def test_event_kind_restricts_the_sum() -> None:
    events = [event("10001", 6000, 1), Event(entity_id="10001", kind="outflow", created_at=NOW, amount=6000)]
    alerts = ThresholdBreachChecker(row(event_kind="outflow"), now=NOW).check(events)
    assert alerts[0].context["total"] == 6000


def test_vip_gate_uses_the_latest_event() -> None:
    checker = ThresholdBreachChecker(row(check_vip_users=False), now=NOW)
    assert checker.check([event("10001", 6000, 1, is_vip=True)]) == []
    assert len(checker.check([event("10002", 6000, 1, is_vip=False)])) == 1


def test_segment_and_region_gates() -> None:
    gated = {**row(), "segments": ["Business__34"], "regions": ["eu"]}
    checker = ThresholdBreachChecker(gated, now=NOW)
    assert checker.check([event("10001", 6000, 1, region="EU", segments=("Business__33",))]) == []
    assert checker.check([event("10001", 6000, 1, region="LATAM", segments=("Business__34",))]) == []
    assert len(checker.check([event("10001", 6000, 1, region="EU", segments=("Business__34",))])) == 1


def test_suppression_lasts_one_window() -> None:
    suppression = Suppression()
    first = ThresholdBreachChecker(row(), now=NOW, suppression=suppression).check([event("10001", 6000, 1)])
    assert len(first) == 1
    assert suppression.keys() == ["DEMO:threshold_breach:10001"]
    again = ThresholdBreachChecker(row(), now=NOW + timedelta(hours=23), suppression=suppression)
    assert again.check([event("10001", 6000, 1), event("10001", 6000, 0)]) == []
    later = ThresholdBreachChecker(row(), now=NOW + timedelta(hours=25), suppression=suppression)
    assert (
        len(later.check([Event(entity_id="10001", kind="inflow", created_at=NOW + timedelta(hours=24), amount=6000)]))
        == 1
    )


def test_config_hooks() -> None:
    assert ThresholdBreachChecker.REQUIRED_CONFIG_KEYS == {"monitoring_window_hours", "threshold"}
    assert ThresholdBreachChecker.CONFIG_VALUE_BOUNDS["monitoring_window_hours"] == (1, 168)
    assert ThresholdBreachChecker.config_warnings({"check_vip_users": False, "check_non_vip_users": False})
    assert ThresholdBreachChecker.config_warnings({}) == []
