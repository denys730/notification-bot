"""heartbeat — one test per scenario of openspec/specs/checkers/heartbeat/spec.md."""

from datetime import UTC, datetime

from checkers import HeartbeatChecker
from checkers.base import Event

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
ROW = {"brand": "DEMO", "checker_name": "Heartbeat", "config": {}}


def test_all_dependencies_reachable() -> None:
    assert HeartbeatChecker(ROW, now=NOW).probe({"mongo": lambda: True, "slack": lambda: True}) is None


def test_stops_at_the_first_failure() -> None:
    probed: list[str] = []

    def probe(name: str, ok: bool):
        def _run() -> bool:
            probed.append(name)
            return ok

        return _run

    alert = HeartbeatChecker(ROW, now=NOW).probe({"mongo": probe("mongo", False), "slack": probe("slack", True)})
    assert alert is not None and alert.service_alert
    assert alert.context["dependency"] == "mongo" and alert.entity_id == "DEMO"
    assert probed == ["mongo"]


def test_a_raising_probe_is_a_failure() -> None:
    def boom() -> bool:
        raise ConnectionError("refused")

    alert = HeartbeatChecker(ROW, now=NOW).probe({"slack": boom})
    assert alert is not None and "ConnectionError" in alert.context["detail"]


def test_events_are_not_an_input() -> None:
    assert HeartbeatChecker(ROW, now=NOW).check([Event(entity_id="1", kind="x", created_at=NOW)]) == []
    assert HeartbeatChecker.REQUIRED_CONFIG_KEYS == frozenset()
