"""The data tools over the seeded in-memory Mongo, including the cadmin grant gate."""

import pytest
import pytest_asyncio

from mcp_server import storage
from mcp_server.auth.principal import AccessDenied, GrantedService, Principal, set_principal
from mcp_server.tools.alerts import get_alert, list_alerts
from mcp_server.tools.journal import get_alert_journal_event, list_alert_journal
from mcp_server.tools.segments import (
    count_players_by_segment,
    filter_players_by_segment,
    get_player_current_segments,
    list_player_segments,
    list_segments,
    validate_segments,
)
from mcp_server.tools.topology import list_clusters


@pytest_asyncio.fixture
async def mcp_store(seeded_store):
    storage.set_client(seeded_store.client)
    report = await storage.discover_brands()
    assert report["discovered"] == ["ACME", "DEMO"]
    yield seeded_store
    set_principal(None)
    storage.set_client(None)


async def test_clusters_and_alerts(mcp_store) -> None:
    clusters = await list_clusters()
    assert clusters["clusters"][0]["brands"] == ["ACME", "DEMO"] and "identity" not in clusters

    rows = await list_alerts(brand="demo")
    assert len(rows) == 5 and all(row["cluster"] == "demo" and len(row["id"]) == 24 for row in rows)
    assert len(await list_alerts(brand="DEMO", checker_code="threshold_breach")) == 2
    assert [r["checker_name"] for r in await list_alerts(brand="DEMO", name_contains="stuck")] == [
        "Status Stuck 120m EU"
    ]
    assert len(await list_alerts()) == 10

    one = await get_alert(rows[0]["id"], brand="DEMO")
    assert one["checker_name"] == rows[0]["checker_name"]
    with pytest.raises(ValueError, match="not on this server"):
        await list_alerts(brand="NOPE")


async def test_grants_scope_every_read(mcp_store) -> None:
    principal = Principal(
        user_id="u1",
        email="ops@example.com",
        is_superuser=False,
        brands=frozenset({"ACME"}),
        services=(GrantedService(slug="alert-bot-acme", name="Alert Bot · Acme", brand="ACME"),),
    )
    set_principal(principal)
    clusters = await list_clusters()
    assert clusters["identity"] == "ops@example.com" and clusters["clusters"][0]["brands"] == ["ACME"]
    assert clusters["granted_services"][0]["slug"] == "alert-bot-acme"
    assert {row["brand"] for row in await list_alerts()} == {"ACME"}
    with pytest.raises(AccessDenied, match="Granted brands: ACME"):
        await list_alerts(brand="DEMO")
    demo_row = (await mcp_store.checkers.find_one({"brand": "DEMO"}))["_id"]
    with pytest.raises(AccessDenied):
        await get_alert(str(demo_row))


async def test_journal(mcp_store) -> None:
    events = await list_alert_journal(brand="DEMO", checker_code="threshold_breach")
    assert len(events) == 6 and "text" not in events[0] and "resolved_config" not in events[0]
    with_text = await list_alert_journal(brand="DEMO", status="partial", include_text=True)
    assert with_text[0]["checker_code"] == "heartbeat" and with_text[0]["text"].startswith("Heartbeat")
    full = await get_alert_journal_event(brand="DEMO", event_id=events[0]["id"])
    assert full["resolved_config"]["checker_name"] == "Threshold Breach 5000 24h"
    since = await list_alert_journal(brand="DEMO", since="2000-01-01T00:00:00Z", limit=3)
    assert len(since) == 3
    with pytest.raises(ValueError, match="Invalid status"):
        await list_alert_journal(brand="DEMO", status="sent")


async def test_segments(mcp_store) -> None:
    premium = await list_segments("DEMO", query="premium")
    assert len(premium) == 1 and premium[0]["segments"] == [
        {"value": "34", "name": "Premium", "label": "Business Premium (34)", "config_entry": "Business__34"}
    ]
    ok = await validate_segments("DEMO", ["Business__34"])
    assert ok["valid"]
    bad = await validate_segments("DEMO", ["Business__Premium", "business__34", "Nope__1"])
    assert not bad["valid"] and "Did you mean: ['Business__34 (name: Premium)']" in bad["errors"][0]
    assert "case-sensitive" in bad["errors"][1]

    moved = await get_player_current_segments("DEMO", "10002")
    assert moved["config_entries"] == ["Business__32"]  # the removed Premium assignment is honoured
    history = await list_player_segments("DEMO", player_id="10002")
    assert [row["action"] for row in history] == ["add", "remove", "add"]
    assert len(await list_player_segments("DEMO", player_id="10002", include_removals=False)) == 2

    who = await filter_players_by_segment("DEMO", ["Business__34"])
    assert who["matched_players"] == ["10001", "10003"] and who["checked_segments"] == ["Business Premium (34)"]
    narrowed = await filter_players_by_segment("DEMO", ["Business__34"], player_ids=["10001", "10002"])
    assert narrowed["matched_players"] == ["10001"] and narrowed["candidates"] == 2

    breakdown = await count_players_by_segment("DEMO", segmentation_id="Business")
    counts = {row["label"]: row["players"] for row in breakdown["breakdown"]}
    assert counts["Business Premium (34)"] == 2 and counts["Business Neutral (32)"] == 1
    with pytest.raises(ValueError):
        await count_players_by_segment("DEMO")
