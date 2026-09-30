"""status_stuck — one test per scenario of openspec/specs/checkers/status-stuck/spec.md."""

from datetime import UTC, datetime, timedelta

from checkers import StatusStuckChecker, Suppression
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def row(**config):
    base = {"pending_minutes": 120}
    base.update(config)
    return {"brand": "DEMO", "checker_name": "SS", "config": base}


def event(entity: str, minutes_ago: float, status: str = "pending", **kw) -> Event:
    return Event(entity_id=entity, kind="outflow", created_at=NOW - timedelta(minutes=minutes_ago), status=status, **kw)


def test_pending_for_too_long_alerts() -> None:
    alerts = StatusStuckChecker(row(), now=NOW).check([event("10005", 180)])
    assert [a.entity_id for a in alerts] == ["10005"]
    assert alerts[0].context["stuck_minutes"] == 180 and alerts[0].context["status"] == "pending"
    assert {"status", "stuck_minutes", "pending_minutes", "since"} <= set(alerts[0].context)


def test_pending_but_fresh_is_silent() -> None:
    assert StatusStuckChecker(row(), now=NOW).check([event("10005", 60)]) == []


def test_final_latest_event_is_silent_whatever_came_before() -> None:
    events = [event("10005", 300), event("10005", 10, status="success")]
    assert StatusStuckChecker(row(), now=NOW).check(events) == []


def test_custom_pending_statuses() -> None:
    checker = StatusStuckChecker(row(pending_statuses=["review"]), now=NOW)
    assert checker.check([event("10005", 300)]) == []
    assert len(checker.check([event("10005", 300, status="review")])) == 1


def test_audience_gates_apply() -> None:
    gated = {**row(check_vip_users=False), "regions": ["EU"]}
    checker = StatusStuckChecker(gated, now=NOW)
    assert checker.check([event("10005", 300, is_vip=True, region="EU")]) == []
    assert checker.check([event("10005", 300, region="LATAM")]) == []
    assert len(checker.check([event("10005", 300, region="EU")])) == 1


def test_suppression_ttl() -> None:
    suppression = Suppression()
    assert (
        len(StatusStuckChecker(row(cache_ttl_hours=1), now=NOW, suppression=suppression).check([event("10005", 300)]))
        == 1
    )
    assert (
        StatusStuckChecker(row(cache_ttl_hours=1), now=NOW + timedelta(minutes=30), suppression=suppression).check(
            [event("10005", 330)]
        )
        == []
    )
    assert (
        len(
            StatusStuckChecker(row(cache_ttl_hours=1), now=NOW + timedelta(minutes=61), suppression=suppression).check(
                [event("10005", 361)]
            )
        )
        == 1
    )


def test_config_hooks() -> None:
    assert StatusStuckChecker.REQUIRED_CONFIG_KEYS == {"pending_minutes"}
    assert StatusStuckChecker.config_warnings({"pending_minutes": 120, "cache_ttl_hours": 1})
    assert StatusStuckChecker.config_warnings({"pending_minutes": 120}) == []
    assert StatusStuckChecker.config_warnings({"pending_minutes": "x"}) == []
