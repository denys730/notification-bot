"""Alerts the bot actually sent — the per-brand alert journal (seeded, in this demo)."""

from typing import Any

from bson import ObjectId

from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.storage import (
    ALERT_JOURNAL_COLLECTION,
    brand_collection,
    doc_to_alert,
    parse_instant,
    resolve,
    validate_checker_code,
)

JOURNAL_HEAVY_FIELDS = ("text", "resolved_config")


@mcp.tool(title="Alerts actually sent", annotations=READ_ONLY_TOOL)
async def list_alert_journal(
    brand: str,
    checker_code: str | None = None,
    player_id: str | None = None,
    entity_id: str | None = None,
    correlation_id: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_text: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Alerts the bot SENT for a brand — one row per alert event, newest first.

    Answers "how many alerts fired, for what, when, and did they arrive". `status` is one of
    delivered / partial / failed. `correlation_id` groups one ongoing situation across runs; `run_id`
    groups everything one checker execution sent. `since` / `until` are ISO-8601 instants. The
    message body and the configuration snapshot are omitted unless `include_text=True`, or use
    `get_alert_journal_event` for the complete document.
    """
    brand = resolve(brand)
    query: dict[str, Any] = {}
    if checker_code:
        query["checker_code"] = validate_checker_code(checker_code)
    if player_id:
        query["player_id"] = player_id
    if entity_id:
        query["entity_id"] = entity_id
    if correlation_id:
        query["correlation_id"] = correlation_id
    if run_id:
        query["run_id"] = run_id
    if status:
        allowed = {"delivered", "partial", "failed"}
        value = status.strip().lower()
        if value not in allowed:
            raise ValueError(f"Invalid status '{status}'. Valid: {sorted(allowed)}")
        query["status"] = value
    window: dict[str, Any] = {}
    if since:
        window["$gte"] = parse_instant(since, "since")
    if until:
        window["$lte"] = parse_instant(until, "until")
    if window:
        query["created_at"] = window
    hidden = [field for field in JOURNAL_HEAVY_FIELDS if not (include_text and field == "text")]
    limit = max(1, min(limit, 500))
    cursor = brand_collection(brand, ALERT_JOURNAL_COLLECTION).find(query, {f: 0 for f in hidden})
    docs = await cursor.sort([("created_at", -1)]).limit(limit).to_list(length=limit)
    return [doc_to_alert(doc) for doc in docs]


@mcp.tool(title="One sent alert in full", annotations=READ_ONLY_TOOL)
async def get_alert_journal_event(brand: str, event_id: str) -> dict[str, Any]:
    """One sent-alert event in full, including the message body and the configuration snapshot."""
    brand = resolve(brand)
    try:
        object_id = ObjectId(event_id)
    except Exception:
        raise ValueError(f"Invalid event_id '{event_id}'")
    doc = await brand_collection(brand, ALERT_JOURNAL_COLLECTION).find_one({"_id": object_id})
    if not doc:
        raise ValueError(f"Alert event '{event_id}' not found for brand '{brand}'")
    return doc_to_alert(doc)
