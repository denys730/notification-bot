from urllib.parse import urlsplit

import pytest

from mcp_server.tools.proposals import decode_proposal, encode_proposal, propose_alert_changes, validate_change

OID = "6a99f6a7157bcb95952e5b17"


def test_round_trip() -> None:
    proposal = {
        "v": 1,
        "service": "alert-bot-demo",
        "brand": "DEMO",
        "changes": [{"id": OID, "set": {"enabled": False}}],
    }
    token = encode_proposal(proposal)
    assert "=" not in token and decode_proposal(token) == proposal


def test_validate_change_names_every_problem() -> None:
    errors: list[str] = []
    validate_change(0, {"id": "short", "set": {"threshold": 1}, "code": "large_deposit"}, errors)
    joined = "\n".join(errors)
    assert "24-character hex" in joined
    assert "'threshold' is not a key cadmin applies — alert knobs belong inside set.config" in joined
    assert "Invalid checker_code 'large_deposit'" in joined
    assert "'reason' is missing" in joined

    errors = []
    validate_change(1, {"set": {"config": {"threshold": 1}}, "reason": "x"}, errors)
    assert any("needs 'code'" in e for e in errors) and any("set.checker_name" in e for e in errors)

    errors = []
    validate_change(2, {"op": "delete", "reason": "x"}, errors)
    assert errors == ["changes[2]: a delete needs the alert's id"]

    errors = []
    validate_change(3, {"id": OID, "op": "upsert", "set": {"config": {"threshold": 1}}, "reason": "evidence"}, errors)
    assert errors == []


async def test_propose_builds_a_decodable_link() -> None:
    result = await propose_alert_changes(
        brand="demo",
        service_slug="alert-bot-demo",
        changes=[
            {
                "id": OID,
                "name": "Threshold Breach 5000 24h",
                "code": "threshold_breach",
                "reason": "6 fires in 5 days",
                "set": {"config": {"threshold": 5500}},
            }
        ],
        title="Raise the threshold",
    )
    assert result["link"].startswith("https://cadmin.test/s/alert-bot-demo/checkers/review#")
    payload = decode_proposal(urlsplit(result["link"]).fragment)
    assert (
        payload["brand"] == "DEMO"
        and payload["service"] == "alert-bot-demo"
        and payload["title"] == "Raise the threshold"
    )
    assert payload["changes"][0]["set"] == {"config": {"threshold": 5500}}
    assert result["summary"] == [
        {"kind": "update", "alert": "Threshold Breach 5000 24h", "reason": "6 fires in 5 days"}
    ]

    override = await propose_alert_changes(
        brand="DEMO",
        service_slug="alert-bot-demo",
        cadmin_base="https://cadmin.test/",
        changes=[
            {
                "code": "status_stuck",
                "reason": "requested",
                "set": {"checker_name": "New", "config": {"pending_minutes": 30}},
            }
        ],
    )
    assert override["link"].startswith("https://cadmin.test/s/") and override["summary"][0]["kind"] == "create"


async def test_propose_refuses_bad_input() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        await propose_alert_changes(brand="DEMO", service_slug="alert-bot-demo", changes=[])
    with pytest.raises(ValueError, match="service_slug is required"):
        await propose_alert_changes(
            brand="DEMO", service_slug=" ", changes=[{"id": OID, "set": {"enabled": True}, "reason": "x"}]
        )
