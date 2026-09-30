"""Guards for "adding a checker" in CLAUDE.md: enum, class, catalogue row and spec must all exist and agree."""

from datetime import UTC, datetime
from pathlib import Path

from checkers import ALL_CHECKERS, checker_for_code
from checkers.catalogue import default_rows
from checkers.sample_events import sample_events
from constants import CheckerCodes

SPECS = Path(__file__).resolve().parent.parent / "openspec" / "specs" / "checkers"


def test_every_code_has_exactly_one_class() -> None:
    claimed = [cls.CHECKER_CODE for cls in ALL_CHECKERS]
    assert sorted(claimed) == sorted(CheckerCodes)
    assert len(claimed) == len(set(claimed))
    for code in CheckerCodes:
        assert checker_for_code(code.value) is not None
    assert checker_for_code("nope") is None and checker_for_code(None) is None


def test_every_code_has_a_spec() -> None:
    for code in CheckerCodes:
        spec = SPECS / code.value.replace("_", "-") / "spec.md"
        assert spec.exists(), f"{code.value} has no spec at {spec}"
        text = spec.read_text(encoding="utf-8")
        assert text.startswith("## Purpose") and "### Requirement:" in text and "- **WHEN**" in text


def test_catalogue_rows_satisfy_their_checker() -> None:
    rows = default_rows("demo")
    assert {row["checker_code"] for row in rows} == {code.value for code in CheckerCodes}
    assert len({row["checker_name"] for row in rows}) == len(rows)
    for row in rows:
        assert row["brand"] == "DEMO"
        cls = checker_for_code(row["checker_code"])
        assert cls is not None
        assert not (cls.REQUIRED_CONFIG_KEYS - set(row["config"])), row["checker_name"]
        for knob, (minimum, maximum) in cls.CONFIG_VALUE_BOUNDS.items():
            value = float(row["config"][knob])
            assert minimum is None or value >= minimum
            assert maximum is None or value <= maximum


def test_validation_hooks_are_well_formed() -> None:
    for cls in ALL_CHECKERS:
        assert set(cls.CONFIG_VALUE_BOUNDS) <= cls.REQUIRED_CONFIG_KEYS, cls.__name__
        assert set(cls.CONFIG_BOUND_REASONS) <= set(cls.CONFIG_VALUE_BOUNDS), cls.__name__
        assert isinstance(cls.config_warnings({}), list)


def test_sample_events_drive_every_catalogue_row() -> None:
    now = datetime.now(UTC)
    events = sample_events(now)
    raised = {}
    for row in default_rows("DEMO"):
        cls = checker_for_code(row["checker_code"])
        raised[row["checker_name"]] = cls(row, now=now).check(events)
    assert {a.entity_id for a in raised["Threshold Breach 5000 24h"]} == {"10001", "10003"}
    assert [a.entity_id for a in raised["Status Stuck 120m EU"]] == ["10005"]
    assert [a.entity_id for a in raised["Activity Drop 50% 30m"]] == ["DEMO"]
    assert [a.entity_id for a in raised["New Entity Breach 1000 24h"]] == ["10006"]
    assert raised["Heartbeat"] == []
