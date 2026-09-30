import pytest

from mcp_server.tools.checker_types import describe_alert_contract, describe_checker_type, list_checker_types


async def test_every_type_is_specified() -> None:
    types = await list_checker_types()
    assert [t["checker_code"] for t in types] == ["activity_drop", "heartbeat", "status_stuck", "threshold_breach"]
    assert all(t["specified"] and t["purpose"] and t["spec"].startswith("openspec/specs/checkers/") for t in types)


async def test_describe_a_type_and_one_requirement() -> None:
    full = await describe_checker_type("threshold_breach")
    names = [item["requirement"] for item in full["outline"]]
    assert "Threshold breach suppression" in names and full["markdown"].startswith("## Purpose")
    one = await describe_checker_type("threshold_breach", requirement="suppression")
    assert one["requirement"]["name"] == "Threshold breach suppression" and "markdown" not in one
    with pytest.raises(ValueError, match="Invalid checker_code"):
        await describe_checker_type("large_deposit")
    with pytest.raises(ValueError, match="No requirement matching"):
        await describe_checker_type("heartbeat", requirement="payments")


async def test_contract_outline() -> None:
    contract = await describe_alert_contract()
    names = [item["requirement"] for item in contract["outline"]]
    assert {"Per-brand checker configuration", "Alert deduplication", "Region audience gate"} <= set(names)
    assert "markdown" not in contract
    one = await describe_alert_contract(requirement="deduplication")
    assert "{brand}:{checker_code}:{entity_id}" in one["requirement"]["markdown"]
