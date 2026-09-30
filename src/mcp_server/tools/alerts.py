"""A brand's configured alerts — rows of the shared `checkers_configs` collection."""

import re
from typing import Any

from bson import ObjectId

from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.auth.principal import current_principal
from mcp_server.storage import checkers_collection, doc_to_alert, readable_brands, resolve, validate_checker_code


@mcp.tool(title="List configured alerts", annotations=READ_ONLY_TOOL)
async def list_alerts(
    brand: str | None = None,
    checker_code: str | None = None,
    enabled: bool | None = None,
    name_contains: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List a brand's configured alerts (checker configs).

    `name_contains` is a case-insensitive substring match on checker_name. One brand can have
    several rows of the same `checker_code` — different thresholds, windows or channels. Without
    `brand`, answers over every brand you are granted.
    """
    query: dict[str, Any] = {}
    if brand:
        query["brand"] = resolve(brand)
    else:
        scope = readable_brands()
        if scope is not None:
            query["brand"] = {"$in": sorted(scope)}
    if checker_code:
        query["checker_code"] = validate_checker_code(checker_code)
    if enabled is not None:
        query["enabled"] = enabled
    if name_contains:
        query["checker_name"] = {"$regex": re.escape(name_contains), "$options": "i"}
    limit = max(1, min(limit, 500))
    cursor = checkers_collection().find(query).sort([("brand", 1), ("checker_name", 1)]).limit(limit)
    return [doc_to_alert(doc) for doc in await cursor.to_list(length=limit)]


@mcp.tool(title="Get one alert", annotations=READ_ONLY_TOOL)
async def get_alert(alert_id: str, brand: str | None = None) -> dict[str, Any]:
    """Get a single configured alert by its Mongo ObjectId."""
    try:
        object_id = ObjectId(alert_id)
    except Exception:
        raise ValueError(f"Invalid alert_id '{alert_id}'")
    query: dict[str, Any] = {"_id": object_id}
    if brand:
        query["brand"] = resolve(brand)
    doc = await checkers_collection().find_one(query)
    if not doc:
        raise ValueError(f"Alert '{alert_id}' not found" + (f" for brand '{brand}'" if brand else ""))
    if not brand:
        principal = current_principal()
        if principal is not None:
            principal.require(str(doc.get("brand") or ""))
    return doc_to_alert(doc)
