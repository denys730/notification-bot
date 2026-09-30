"""Where each brand's data lives, and how the API reaches it.

The layout: one shared `alert_bot_system` database holding every brand's checker
rows, plus one `alert_bot_<brand>` database per brand for everything else. The MCP server discovers
brands from that naming, so it must not change.

No ODM. The routers work with plain documents through motor collections, which is also what lets
the unit tests run against an in-memory Mongo (`mongomock_motor`) without touching the routers.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

SYSTEM_DB_NAME = "alert_bot_system"
BRAND_DB_PREFIX = "alert_bot_"

CHECKERS_COLLECTION = "checkers_configs"
GLOBAL_SETTINGS_COLLECTION = "global_settings"
SEGMENTATIONS_COLLECTION = "segmentations"
PLAYER_SEGMENTS_COLLECTION = "player_segments"
ALERT_JOURNAL_COLLECTION = "alert_journal"


def brand_db_name(brand: str) -> str:
    return f"{BRAND_DB_PREFIX}{brand.strip().lower()}"


def brand_from_db_name(name: str) -> str | None:
    """The brand a database name carries, or None for `alert_bot_system` and unrelated databases."""
    if name == SYSTEM_DB_NAME or not name.startswith(BRAND_DB_PREFIX):
        return None
    brand = name[len(BRAND_DB_PREFIX) :]
    return brand.upper() if brand else None


class MongoStore:
    """Collection addressing over one Mongo client. Holds no state of its own."""

    def __init__(self, client: AsyncIOMotorClient) -> None:
        self.client = client

    @property
    def system_db(self) -> AsyncIOMotorDatabase:
        return self.client[SYSTEM_DB_NAME]

    def brand_db(self, brand: str) -> AsyncIOMotorDatabase:
        return self.client[brand_db_name(brand)]

    @property
    def checkers(self) -> AsyncIOMotorCollection:
        return self.system_db[CHECKERS_COLLECTION]

    def global_settings(self, brand: str) -> AsyncIOMotorCollection:
        return self.brand_db(brand)[GLOBAL_SETTINGS_COLLECTION]

    def segmentations(self, brand: str) -> AsyncIOMotorCollection:
        return self.brand_db(brand)[SEGMENTATIONS_COLLECTION]

    def player_segments(self, brand: str) -> AsyncIOMotorCollection:
        return self.brand_db(brand)[PLAYER_SEGMENTS_COLLECTION]

    def alert_journal(self, brand: str) -> AsyncIOMotorCollection:
        return self.brand_db(brand)[ALERT_JOURNAL_COLLECTION]

    async def ensure_indexes(self, brands: list[str]) -> None:
        """The indexes the routers rely on. `(brand, checker_name)` is unique per the contract spec."""
        await self.checkers.create_index([("brand", ASCENDING), ("checker_name", ASCENDING)], unique=True)
        for brand in brands:
            await self.global_settings(brand).create_index([("name", ASCENDING)], unique=True)
            await self.segmentations(brand).create_index([("segmentation_id", ASCENDING)], unique=True)
            await self.player_segments(brand).create_index(
                [("segmentation_id", ASCENDING), ("player_id", ASCENDING), ("timestamp", DESCENDING)]
            )
            await self.alert_journal(brand).create_index([("created_at", DESCENDING)])

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:
            return False
