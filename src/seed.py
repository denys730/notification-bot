"""Demo data: checker rows, settings, a segmentation catalogue, player assignments and an alert journal.

Idempotent per brand — a brand that already holds checker rows is left alone unless `force` is
set. A production alerting service would leave seeding to operators; the demo does it, because an
empty demo shows nothing.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from checkers.catalogue import default_rows
from checkers.sample_events import ENTITIES
from constants import ALERT_STATUS_DELIVERED, ALERT_STATUS_PARTIAL, CUSTOM_SEGMENTATION_PRODUCT, GlobalSettingNames
from storage.mongo import MongoStore

DEMO_REGIONS = ["EU", "LATAM", "ASIA"]
DEMO_DEFAULT_REGION = "EU"
WATCHLIST_SEGMENTATION_ID = "5f1c2f3a9d4b4c8e8a6d1f2e3b4c5d6e"
OPERATOR_ID = "op-demo"
JOURNAL_TTL = timedelta(days=180)


def demo_segmentations(brand: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "segmentation_id": "Business",
            "brand": brand,
            "operator_id": OPERATOR_ID,
            "product": "business",
            "name": "Business",
            "description": "How much an entity is worth to the business, recalculated nightly.",
            "segments": [
                {"value": "31", "name": "Negative", "description": "Costs more than it brings"},
                {"value": "32", "name": "Neutral", "description": "Breaks even"},
                {"value": "33", "name": "Positive", "description": "Profitable"},
                {"value": "34", "name": "Premium", "description": "Top decile by value"},
            ],
            "created_at": now - timedelta(days=90),
        },
        {
            "segmentation_id": "Casino",
            "brand": brand,
            "operator_id": OPERATOR_ID,
            "product": "casino",
            "name": "Casino tier",
            "description": "Loyalty tier on the casino product.",
            "segments": [
                {"value": "vip_bronze", "name": "VIP-Bronze", "description": None},
                {"value": "vip_silver", "name": "VIP-Silver", "description": None},
                {"value": "vip_gold", "name": "VIP-Gold", "description": None},
            ],
            "created_at": now - timedelta(days=60),
        },
        {
            "segmentation_id": WATCHLIST_SEGMENTATION_ID,
            "brand": brand,
            "operator_id": None,
            "product": CUSTOM_SEGMENTATION_PRODUCT,
            "name": "Watchlist Q3",
            "description": "Imported from a CSV by the operations team.",
            "segments": [
                {"value": "1", "name": "Watch", "description": None},
                {"value": "2", "name": "Review", "description": None},
            ],
            "created_at": now - timedelta(days=10),
        },
    ]


def demo_player_segments(brand: str, now: datetime) -> list[dict[str, Any]]:
    def assignment(
        player_id: str, segmentation_id: str, segment: str, product: str, days_ago: int, action: str = "add"
    ):
        moment = now - timedelta(days=days_ago)
        return {
            "brand": brand,
            "player_id": player_id,
            "segmentation_id": segmentation_id,
            "segment": segment,
            "product": product,
            "action": action,
            "valid_from": moment,
            "valid_to": None,
            "timestamp": moment,
            "created_at": moment,
        }

    rows: list[dict[str, Any]] = []
    for player_id, profile in ENTITIES.items():
        for entry in profile["segments"]:
            segmentation_id, _, value = entry.partition("__")
            product = "business" if segmentation_id == "Business" else "casino"
            rows.append(assignment(player_id, segmentation_id, value, product, days_ago=7))
    # A move: 10002 used to be Premium and was re-segmented to Neutral a week ago.
    rows.append(assignment("10002", "Business", "34", "business", days_ago=40))
    rows.append(assignment("10002", "Business", "34", "business", days_ago=8, action="remove"))
    # A removed casino tier, so the raw history shows a removal.
    rows.append(assignment("10004", "Casino", "vip_bronze", "casino", days_ago=30))
    rows.append(assignment("10004", "Casino", "vip_bronze", "casino", days_ago=3, action="remove"))
    # The custom watchlist.
    rows.append(assignment("10003", WATCHLIST_SEGMENTATION_ID, "1", CUSTOM_SEGMENTATION_PRODUCT, days_ago=10))
    rows.append(assignment("10004", WATCHLIST_SEGMENTATION_ID, "2", CUSTOM_SEGMENTATION_PRODUCT, days_ago=10))
    return rows


def _journal_event(
    row: dict[str, Any],
    *,
    entity_id: str,
    player_id: str | None,
    text: str,
    context: dict[str, Any],
    at: datetime,
    ok: bool = True,
    error: str | None = None,
) -> dict[str, Any]:
    channels = row.get("channels") or ([row["channel"]] if row.get("channel") else [])
    deliveries = [
        {
            "transport": "slack",
            "channel": channel,
            "ok": ok if index == 0 else True,
            "ts": f"{int(at.timestamp())}.{index:06d}",
            "thread_ts": None,
            "error": error if (index == 0 and not ok) else None,
            "text": None,
        }
        for index, channel in enumerate(channels)
    ]
    status = ALERT_STATUS_DELIVERED if all(d["ok"] for d in deliveries) else ALERT_STATUS_PARTIAL
    return {
        "brand": row["brand"],
        "checker_code": row["checker_code"],
        "checker_name": row["checker_name"],
        "run_id": uuid.uuid4().hex,
        "run_started_at": at - timedelta(seconds=3),
        "status": status,
        "correlation_id": f"{row['brand']}:{row['checker_code']}:{entity_id}",
        "uniq_alert_id": uuid.uuid4().hex,
        "entity_id": entity_id,
        "player_id": player_id,
        "operator_id": OPERATOR_ID,
        "text": text,
        "requested_channels": channels,
        "deliveries": deliveries,
        "is_threaded_reply": False,
        "reply_to": None,
        "context": context,
        "resolved_config": {
            "checker_name": row["checker_name"],
            "config": row["config"],
            "channels": channels,
            "segments": row.get("segments"),
            "regions": row.get("regions"),
        },
        "created_at": at,
        "expired_at": at + JOURNAL_TTL,
    }


def demo_alert_journal(brand: str, rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    by_name = {row["checker_name"]: row for row in rows}
    threshold = by_name["Threshold Breach 5000 24h"]
    stuck = by_name["Status Stuck 120m EU"]
    drop = by_name["Activity Drop 50% 30m"]
    heartbeat = by_name["Heartbeat"]
    events: list[dict[str, Any]] = []

    for entity_id, total, count, hours_ago in (
        ("10003", 5200.0, 1, 6),
        ("10001", 5700.0, 6, 26),
        ("10003", 6100.0, 3, 50),
        ("10005", 5050.0, 4, 98),
        ("10001", 5320.0, 5, 74),
        ("10003", 8000.0, 2, 122),
    ):
        at = now - timedelta(hours=hours_ago)
        events.append(
            _journal_event(
                threshold,
                entity_id=entity_id,
                player_id=entity_id,
                text=(
                    f"Threshold breach on {brand}: entity {entity_id} reached {total:,.2f} over 24h "
                    f"(threshold 5,000.00, {count} events)"
                ),
                context={
                    "total": total,
                    "threshold": 5000,
                    "window_hours": 24,
                    "events": count,
                    "window_start": (at - timedelta(hours=24)).isoformat(),
                    "window_end": at.isoformat(),
                },
                at=at,
            )
        )
    for entity_id, minutes, hours_ago in (("10005", 185, 12), ("10002", 240, 30), ("10005", 400, 70)):
        at = now - timedelta(hours=hours_ago)
        events.append(
            _journal_event(
                stuck,
                entity_id=entity_id,
                player_id=entity_id,
                text=f"Status stuck on {brand}: entity {entity_id} has been 'pending' for {minutes}m (limit 120m)",
                context={"status": "pending", "stuck_minutes": minutes, "pending_minutes": 120},
                at=at,
            )
        )
    for current, baseline, hours_ago in ((4, 11.3, 20), (2, 10.9, 140)):
        at = now - timedelta(hours=hours_ago)
        pct = (1 - current / baseline) * 100
        events.append(
            _journal_event(
                drop,
                entity_id=brand,
                player_id=None,
                text=(
                    f"Activity drop on {brand}: {current} events in the last 30m against a baseline of "
                    f"{baseline:.1f} ({pct:.0f}% drop, threshold 50%)"
                ),
                context={"current": current, "baseline": baseline, "drop_percent": pct, "window_minutes": 30},
                at=at,
            )
        )
    at = now - timedelta(hours=68)
    events.append(
        _journal_event(
            heartbeat,
            entity_id=brand,
            player_id=None,
            text=f"Heartbeat on {brand}: dependency 'slack' is unreachable (probe returned false)",
            context={"dependency": "slack", "service_alert": True},
            at=at,
            ok=False,
            error="channel_not_found",
        )
    )
    return events


async def seed_demo_data(store: MongoStore, brands: list[str], *, force: bool = False) -> dict[str, str]:
    report: dict[str, str] = {}
    now = datetime.now(UTC).replace(microsecond=0)
    for brand in brands:
        brand = brand.upper()
        existing = await store.checkers.count_documents({"brand": brand})
        if existing and not force:
            report[brand] = f"kept ({existing} checker rows already there)"
            continue
        if force:
            await store.checkers.delete_many({"brand": brand})
            for collection in (
                store.global_settings(brand),
                store.segmentations(brand),
                store.player_segments(brand),
                store.alert_journal(brand),
            ):
                await collection.delete_many({})

        rows = default_rows(brand)
        for index, row in enumerate(rows):
            row["created_at"] = now - timedelta(days=30 - index)
            row["updated_at"] = None
        await store.checkers.insert_many(rows)

        for name, value in (
            (GlobalSettingNames.REGIONS, DEMO_REGIONS),
            (GlobalSettingNames.DEFAULT_REGION, DEMO_DEFAULT_REGION),
        ):
            await store.global_settings(brand).update_one({"name": name.value}, {"$set": {"value": value}}, upsert=True)
        await store.segmentations(brand).insert_many(demo_segmentations(brand, now))
        await store.player_segments(brand).insert_many(demo_player_segments(brand, now))
        await store.alert_journal(brand).insert_many(demo_alert_journal(brand, rows, now))
        report[brand] = f"seeded ({len(rows)} checker rows)"
    return report
