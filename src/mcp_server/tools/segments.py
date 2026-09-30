"""A brand's segmentation catalogue and its players' segment assignments.

"Current" membership is resolved ONE way for every tool here — latest assignment per segmentation
by `timestamp`, not removed, inside its validity window — so a player these tools list is a player
the segment gate would let through.
"""

from datetime import UTC, datetime
from typing import Any

from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.storage import (
    PLAYER_SEGMENTS_COLLECTION,
    SEGMENTATIONS_COLLECTION,
    brand_collection,
    describe_segment,
    doc_to_alert,
    load_segment_names,
    resolve,
    segment_label,
    serialize,
    validate_segment_entries,
)


async def load_segmentation_catalog(brand: str) -> list[dict[str, Any]]:
    return await brand_collection(brand, SEGMENTATIONS_COLLECTION).find({}).to_list(length=1000)


def _is_current(doc: dict[str, Any], now: datetime) -> bool:
    if doc.get("action") == "remove":
        return False
    valid_from = doc.get("valid_from")
    valid_to = doc.get("valid_to")
    if valid_from is not None and _aware(valid_from) > now:
        return False
    if valid_to is not None and _aware(valid_to) <= now:
        return False
    return True


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def resolve_current_pairs(docs: list[dict[str, Any]], now: datetime) -> dict[str, set[str]]:
    """`player_id -> {"<segmentation_id>__<value>", ...}` from raw assignment rows."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in sorted(
        docs, key=lambda d: (_aware(d.get("timestamp") or datetime.min.replace(tzinfo=UTC)), str(d.get("_id")))
    ):
        latest[(str(doc.get("player_id")), str(doc.get("segmentation_id")))] = doc
    result: dict[str, set[str]] = {}
    for (player_id, segmentation_id), doc in latest.items():
        if _is_current(doc, now):
            result.setdefault(player_id, set()).add(f"{segmentation_id}__{doc.get('segment')}")
    return result


async def _current_pairs(brand: str, now: datetime, player_ids: list[str] | None = None) -> dict[str, set[str]]:
    query: dict[str, Any] = {}
    if player_ids is not None:
        query["player_id"] = {"$in": sorted(set(player_ids))}
    docs = await brand_collection(brand, PLAYER_SEGMENTS_COLLECTION).find(query).to_list(length=None)
    return resolve_current_pairs(docs, now)


@mcp.tool(title="Segmentation catalogue", annotations=READ_ONLY_TOOL)
async def list_segments(brand: str, query: str | None = None) -> list[dict[str, Any]]:
    """Browse the brand's segmentation catalogue — the valid values for an alert's `segments` field.

    `query` is a case-insensitive substring matched against segmentation ids/names and segment
    values/names. Each segment carries `config_entry` (the exact '{segmentation_id}__{value}' an
    alert's `segments` list takes) and `label` ('Business Premium (34)') to quote in any answer.
    """
    brand = resolve(brand)
    needle = query.strip().lower() if query else None
    result = []
    for doc in await load_segmentation_catalog(brand):
        segmentation_id = doc["segmentation_id"]
        whole_match = needle is not None and (
            needle in segmentation_id.lower() or needle in (doc.get("name") or "").lower()
        )
        matched = [
            {
                "value": s.get("value"),
                "name": s.get("name"),
                "label": segment_label(segmentation_id, s.get("value"), s.get("name")),
                "config_entry": f"{segmentation_id}__{s.get('value')}",
            }
            for s in doc.get("segments", [])
            if needle is None
            or whole_match
            or needle in (s.get("value") or "").lower()
            or needle in (s.get("name") or "").lower()
        ]
        if matched:
            result.append(
                {
                    "segmentation_id": segmentation_id,
                    "segmentation_name": doc.get("name"),
                    "product": doc.get("product"),
                    "created_at": serialize(doc.get("created_at")),
                    "segments": matched,
                }
            )
    return result


@mcp.tool(title="Validate segment entries", annotations=READ_ONLY_TOOL)
async def validate_segments(brand: str, segments: list[str]) -> dict[str, Any]:
    """Check `segments` entries against the brand's catalogue before they go into a config. A pure check."""
    brand = resolve(brand)
    catalog = await load_segmentation_catalog(brand)
    if not catalog:
        return {"valid": False, "errors": [f"No segmentations found for brand '{brand}'."]}
    errors = validate_segment_entries(segments, catalog)
    return {"valid": not errors, "errors": errors, "checked": segments}


@mcp.tool(title="One player's current segments", annotations=READ_ONLY_TOOL)
async def get_player_current_segments(brand: str, player_id: str) -> dict[str, Any]:
    """Which segments ONE player is in right now. For a GROUP use `filter_players_by_segment` or
    `count_players_by_segment` — one aggregation instead of one call per player."""
    brand = resolve(brand)
    now = datetime.now(UTC)
    pairs = (await _current_pairs(brand, now, [player_id])).get(player_id, set())
    names = await load_segment_names(brand)
    segments = []
    for entry in sorted(pairs):
        segmentation_id, sep, value = entry.partition("__")
        if sep:
            segments.append(describe_segment(segmentation_id, value, names))
    return {
        "brand": brand,
        "player_id": player_id,
        "as_of": now.isoformat(),
        "config_entries": sorted(pairs),
        "segments": segments,
    }


@mcp.tool(title="Raw segment history", annotations=READ_ONLY_TOOL)
async def list_player_segments(
    brand: str,
    player_id: str | None = None,
    segmentation_id: str | None = None,
    segment: str | None = None,
    include_expired: bool = True,
    include_removals: bool = True,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Raw segment-assignment history — every row, newest event first. The debugging view, NOT the
    answer to "which segment is this player in"; that is `get_player_current_segments`."""
    brand = resolve(brand)
    query: dict[str, Any] = {}
    if player_id:
        query["player_id"] = player_id
    if segmentation_id:
        query["segmentation_id"] = segmentation_id
    if segment:
        query["segment"] = segment
    if not include_removals:
        query["action"] = {"$ne": "remove"}
    if not include_expired:
        now = datetime.now(UTC)
        query["valid_from"] = {"$lte": now}
        query["$or"] = [{"valid_to": None}, {"valid_to": {"$gt": now}}]
    limit = max(1, min(limit, 1000))
    cursor = brand_collection(brand, PLAYER_SEGMENTS_COLLECTION).find(query).sort([("timestamp", -1), ("_id", -1)])
    return [{**doc_to_alert(doc), "brand": brand} for doc in await cursor.limit(limit).to_list(length=limit)]


@mcp.tool(title="Filter players by segment", annotations=READ_ONLY_TOOL)
async def filter_players_by_segment(
    brand: str, segments: list[str], player_ids: list[str] | None = None, limit: int = 1000
) -> dict[str, Any]:
    """Which players are CURRENTLY in the given segments — one query for the whole group.

    `segments` are '{segmentation_id}__{value}' entries. Pass `player_ids` to narrow to a candidate
    set (the players from `list_alert_journal`, say); omit it for every player of the brand.
    """
    brand = resolve(brand)
    wanted = {entry.strip() for entry in segments if entry and entry.strip()}
    if not wanted:
        raise ValueError("`segments` must hold at least one '{segmentation_id}__{value}' entry")
    for entry in wanted:
        segmentation_id, sep, value = entry.partition("__")
        if not (sep and segmentation_id and value):
            raise ValueError(f"Malformed segment entry '{entry}': expected '{{segmentation_id}}__{{value}}'")
    now = datetime.now(UTC)
    current = await _current_pairs(brand, now, player_ids)
    matched = sorted(player for player, pairs in current.items() if pairs & wanted)
    names = await load_segment_names(brand)
    limit = max(1, min(limit, 10000))
    return {
        "brand": brand,
        "as_of": now.isoformat(),
        "checked_segments": [
            segment_label(
                e.partition("__")[0], e.partition("__")[2], names.get((e.partition("__")[0], e.partition("__")[2]))
            )
            for e in sorted(wanted)
        ],
        "candidates": len(set(player_ids)) if player_ids is not None else None,
        "matched_players": matched[:limit],
        "matched_count": len(matched),
        "truncated": len(matched) > limit,
    }


@mcp.tool(title="Segment breakdown", annotations=READ_ONLY_TOOL)
async def count_players_by_segment(
    brand: str, segmentation_id: str | None = None, player_ids: list[str] | None = None
) -> dict[str, Any]:
    """How many players sit in each segment right now. Pass `player_ids` to break down a specific
    group, `segmentation_id` to narrow to one segmentation. The tool for any "statistics by segment"
    question."""
    brand = resolve(brand)
    if segmentation_id is None and player_ids is None:
        raise ValueError("Pass `segmentation_id` (e.g. 'Business') or `player_ids`.")
    now = datetime.now(UTC)
    current = await _current_pairs(brand, now, player_ids)
    counts: dict[str, int] = {}
    for pairs in current.values():
        for entry in pairs:
            if segmentation_id and entry.partition("__")[0] != segmentation_id.strip():
                continue
            counts[entry] = counts.get(entry, 0) + 1
    names = await load_segment_names(brand)
    breakdown = []
    for entry, players in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        sid, _, value = entry.partition("__")
        breakdown.append({**describe_segment(sid, value, names), "players": players})
    return {
        "brand": brand,
        "as_of": now.isoformat(),
        "scope": "supplied players" if player_ids is not None else "whole brand",
        "candidates": len(set(player_ids)) if player_ids is not None else None,
        "breakdown": breakdown,
    }
