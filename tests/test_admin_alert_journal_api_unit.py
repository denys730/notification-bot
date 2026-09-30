from helpers import encode_filter
from httpx import AsyncClient

JOURNAL = "/api/admin/alert-journal"


async def test_list_is_newest_first_without_the_heavy_fields(client: AsyncClient) -> None:
    body = (await client.get(JOURNAL)).json()
    assert body["meta"]["total_results"] == 12 and body["meta"]["brand"] == "DEMO"
    events = body["alert_events"]
    assert events[0]["created_at"] >= events[-1]["created_at"]
    assert events[0]["text"] is None and events[0]["resolved_config"] is None
    assert events[0]["deliveries"][0]["transport"] == "slack"


async def test_filters_and_includes(client: AsyncClient) -> None:
    token = encode_filter({"checker_code": "threshold_breach"})
    body = (await client.get(JOURNAL, params={"filter": token, "include[]": "text"})).json()
    assert body["meta"]["total_results"] == 6
    assert all(event["text"].startswith("Threshold breach on DEMO") for event in body["alert_events"])
    partial = (await client.get(JOURNAL, params={"filter": encode_filter({"status": "partial"})})).json()
    assert [event["checker_code"] for event in partial["alert_events"]] == ["heartbeat"]
    assert partial["alert_events"][0]["deliveries"][0]["error"] == "channel_not_found"


async def test_single_event_carries_everything(client: AsyncClient) -> None:
    first = (await client.get(JOURNAL)).json()["alert_events"][0]
    body = (await client.get(f"{JOURNAL}/{first['id']}")).json()["alert_event"]
    assert body["text"] and body["resolved_config"]["checker_name"] == first["checker_name"]
    assert (await client.get(f"{JOURNAL}/{'0' * 24}")).status_code == 404
    assert (await client.get(JOURNAL, headers={"X-Brand": ""})).status_code == 400
