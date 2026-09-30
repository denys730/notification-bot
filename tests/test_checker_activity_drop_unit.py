"""activity_drop — one test per scenario of openspec/specs/checkers/activity-drop/spec.md."""

from datetime import UTC, datetime, timedelta

from checkers import ActivityDropChecker, Suppression
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(**config):
    base = {"window_minutes": 30, "baseline_days": 2, "drop_percent": 50, "min_baseline_events": 3}
    base.update(config)
    return {"brand": "DEMO", "checker_name": "AD", "config": base}


def burst(count: int, days_ago: int, region: str = "EU") -> list[Event]:
    end = NOW - timedelta(days=days_ago)
    return [
        Event(entity_id=str(i), kind="session", created_at=end - timedelta(minutes=i), region=region)
        for i in range(count)
    ]


def test_drop_past_the_threshold_alerts_once_for_the_brand() -> None:
    events = burst(2, 0) + burst(10, 1) + burst(10, 2)
    alerts = ActivityDropChecker(row(), now=NOW).check(events)
    assert [a.entity_id for a in alerts] == ["DEMO"]
    assert alerts[0].context["current"] == 2 and alerts[0].context["baseline"] == 10
    assert alerts[0].context["drop_percent"] == 80
    assert {"current", "baseline", "drop_percent", "threshold_percent", "window_minutes", "baseline_days"} <= set(
        alerts[0].context
    )


def test_volume_within_tolerance_is_silent() -> None:
    events = burst(6, 0) + burst(10, 1) + burst(10, 2)
    assert ActivityDropChecker(row(), now=NOW).check(events) == []


def test_thin_baseline_is_not_judged() -> None:
    events = burst(0, 0) + burst(2, 1) + burst(2, 2)
    assert ActivityDropChecker(row(), now=NOW).check(events) == []


def test_gates_restrict_the_cohort_in_every_window() -> None:
    gated = {**row(), "regions": ["EU"]}
    events = burst(2, 0) + burst(10, 1, region="LATAM") + burst(10, 2, region="LATAM")
    assert ActivityDropChecker(gated, now=NOW).check(events) == []  # LATAM baseline is not counted


def test_suppression_for_one_window() -> None:
    suppression = Suppression()
    events = burst(2, 0) + burst(10, 1) + burst(10, 2)
    assert len(ActivityDropChecker(row(), now=NOW, suppression=suppression).check(events)) == 1
    assert ActivityDropChecker(row(), now=NOW + timedelta(minutes=10), suppression=suppression).check(events) == []


def test_config_hooks() -> None:
    assert ActivityDropChecker.REQUIRED_CONFIG_KEYS == {"window_minutes", "baseline_days", "drop_percent"}
    assert ActivityDropChecker.config_warnings({"min_baseline_events": 2})
    assert ActivityDropChecker.config_warnings({}) == []
