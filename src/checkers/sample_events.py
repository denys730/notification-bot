"""A deterministic stream of demo events, so a checker can be run by hand without any data source.

`python src/commands.py run-checker threshold_breach` feeds this to a checker built from the
catalogue row and prints what it would have raised.
"""

from datetime import datetime, timedelta

from checkers.base import Event

ENTITIES = {
    "10001": {"is_vip": True, "region": "EU", "segments": ("Business__34", "Casino__vip_gold")},
    "10002": {"is_vip": False, "region": "EU", "segments": ("Business__32",)},
    "10003": {"is_vip": True, "region": "LATAM", "segments": ("Business__34",)},
    "10004": {"is_vip": False, "region": "ASIA", "segments": ("Business__31",)},
    "10005": {"is_vip": False, "region": "EU", "segments": ("Business__33", "Casino__vip_silver")},
    "10006": {"is_vip": False, "region": None, "segments": ()},
}


def sample_events(now: datetime) -> list[Event]:
    events: list[Event] = []

    def add(
        entity_id: str,
        kind: str,
        minutes_ago: float,
        amount: float = 0.0,
        status: str = "success",
        currency: str | None = None,
        source: str | None = None,
    ) -> None:
        profile = ENTITIES[entity_id]
        created = now - timedelta(minutes=minutes_ago)
        events.append(
            Event(
                entity_id=entity_id,
                kind=kind,
                created_at=created,
                amount=amount,
                status=status,
                is_vip=profile["is_vip"],
                region=profile["region"],
                segments=profile["segments"],
                currency=currency,
                source=source,
            )
        )

    # 10001 drip-feeds past the 5,000 day threshold; 10003 does it in one go inside an hour.
    for step in range(6):
        add("10001", "inflow", minutes_ago=60 * step + 10, amount=950)
    add("10003", "inflow", minutes_ago=20, amount=5200)
    add("10002", "inflow", minutes_ago=90, amount=300)
    add("10002", "inflow", minutes_ago=30, amount=250, status="failed")
    # 10006 registered three hours ago and put 1,500 in straight away; 10003 registered days ago, so
    # its 5,200 is a threshold breach and not a new entity's first amount.
    add("10006", "registration", minutes_ago=180)
    add("10006", "inflow", minutes_ago=120, amount=1500, currency="EUR", source="card")
    add("10003", "registration", minutes_ago=6000)
    # A pending outflow that has been sitting for three hours, and one that is fresh.
    add("10005", "outflow", minutes_ago=180, amount=700, status="pending")
    add("10004", "outflow", minutes_ago=15, amount=120, status="pending")
    # Background "session" volume: a steady baseline over the past week, quiet in the last half hour.
    # 10005 stays out of it so its pending outflow remains its latest event.
    rotation = [entity for entity in ENTITIES if entity != "10005"]
    for day in range(0, 8):
        for slot in range(0, 24 * 60):
            minutes_ago = day * 24 * 60 + slot
            if day == 0 and minutes_ago < 30:
                continue
            entity = rotation[(day + slot) % len(rotation)]
            add(entity, "session", minutes_ago=minutes_ago)
    return events
