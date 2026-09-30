"""One Mongo deployment, brands discovered from it, and the single place brand access is enforced.

A multi-cluster deployment would route each brand to its cluster; the demo has one, named `demo`,
so `list_clusters` keeps a shape that can grow. Every tool reaches its data through `resolve()`, which checks the caller's cadmin
grants — the check lives here rather than in each tool so no future tool can be written without it.
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from constants import CheckerCodes  # type: ignore[import-not-found]
from mcp_server import settings
from mcp_server.auth.principal import Principal, current_principal
from storage.mongo import (  # type: ignore[import-not-found]
    ALERT_JOURNAL_COLLECTION,
    CHECKERS_COLLECTION,
    PLAYER_SEGMENTS_COLLECTION,
    SEGMENTATIONS_COLLECTION,
    SYSTEM_DB_NAME,
    brand_db_name,
    brand_from_db_name,
)

__all__ = [
    "ALERT_JOURNAL_COLLECTION",
    "PLAYER_SEGMENTS_COLLECTION",
    "SEGMENTATIONS_COLLECTION",
    "brand_collection",
    "checkers_collection",
    "describe_segment",
    "discover_brands",
    "doc_to_alert",
    "ensure_discovered",
    "known_brands",
    "load_segment_names",
    "parse_instant",
    "readable_brands",
    "redact_uri",
    "reset",
    "resolve",
    "segment_label",
    "serialize",
    "validate_checker_code",
    "validate_segment_entries",
]

_client: AsyncIOMotorClient | None = None
_brands: tuple[str, ...] = ()
_discovered = False
_lock = asyncio.Lock()


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri(), serverSelectionTimeoutMS=5000)
    return _client


def set_client(client: AsyncIOMotorClient | None) -> None:
    """For tests: install an in-memory client and forget any discovery."""
    global _client
    _client = client
    reset()


def reset() -> None:
    global _brands, _discovered
    _brands = ()
    _discovered = False


def known_brands() -> tuple[str, ...]:
    return _brands


async def discover_brands() -> dict[str, Any]:
    """Every `alert_bot_<brand>` database is a brand. Bounded by our own timeout, not the driver's 30s."""
    global _brands, _discovered
    try:
        names = await asyncio.wait_for(get_client().list_database_names(), timeout=settings.discovery_timeout_seconds())
    except TimeoutError:
        return {"discovered": [], "unreachable": f"did not answer within {settings.discovery_timeout_seconds():.0f}s"}
    except Exception as error:
        return {"discovered": [], "unreachable": f"{type(error).__name__}: {error}"}
    _brands = tuple(sorted({brand for brand in map(brand_from_db_name, names) if brand}))
    _discovered = True
    return {"discovered": list(_brands), "unreachable": None}


async def ensure_discovered() -> dict[str, Any] | None:
    """Discover once per process; concurrent first callers wait for one discovery rather than stampede."""
    if _discovered:
        return None
    async with _lock:
        if _discovered:
            return None
        return await discover_brands()


def checkers_collection() -> AsyncIOMotorCollection:
    return get_client()[SYSTEM_DB_NAME][CHECKERS_COLLECTION]


def brand_collection(brand: str, collection: str) -> AsyncIOMotorCollection:
    return get_client()[brand_db_name(brand)][collection]


def resolve(brand: str) -> str:
    """The brand for this call, upper-cased — and the access gate every tool goes through."""
    wanted = (brand or "").strip().upper()
    if not wanted:
        raise ValueError("`brand` is required")
    principal = current_principal()
    if principal is not None:
        principal.require(wanted)
    if _discovered and wanted not in _brands:
        raise ValueError(
            f"Brand '{wanted}' is not on this server. Known brands: {list(_brands) or 'none discovered'}. "
            f"Brands are read from the database at startup ('alert_bot_<brand>' databases); a brand seeded "
            f"since then needs `list_clusters(refresh=True)`."
        )
    return wanted


def readable_brands(principal: Principal | None = None) -> set[str] | None:
    """The discovered brands this caller may read, or None when nothing restricts them (stdio without a token)."""
    principal = principal or current_principal()
    if principal is None:
        return None
    return {brand for brand in _brands if principal.may_read(brand)}


def redact_uri(uri: str) -> str:
    return re.sub(r"//[^@/]+@", "//***@", uri)


# ---- serialisation and validation ----------------------------------------------------------------


def serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def doc_to_alert(doc: dict[str, Any]) -> dict[str, Any]:
    alert = serialize(doc)
    alert["id"] = alert.pop("_id")
    alert["cluster"] = settings.CLUSTER_NAME
    return alert


def parse_instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid {field} '{value}': expected ISO-8601, e.g. '2026-09-07T03:00:00Z'")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def validate_checker_code(checker_code: str) -> str:
    try:
        return CheckerCodes(checker_code).value
    except ValueError:
        valid = ", ".join(code.value for code in CheckerCodes)
        raise ValueError(f"Invalid checker_code '{checker_code}'. Valid codes: {valid}")


def segment_label(segmentation_id: str, value: str | None, name: str | None) -> str:
    """`Business Premium (34)` — the one rendering of a segment used in answers and reports."""
    if name:
        return f"{segmentation_id} {name} ({value})"
    return f"{segmentation_id} ({value})"


async def load_segment_names(brand: str) -> dict[tuple[str, str], str]:
    docs = await brand_collection(brand, SEGMENTATIONS_COLLECTION).find({}).to_list(length=1000)
    names: dict[tuple[str, str], str] = {}
    for doc in docs:
        for segment in doc.get("segments") or []:
            if segment.get("value") is not None and segment.get("name"):
                names[(doc["segmentation_id"], str(segment["value"]))] = segment["name"]
    return names


def describe_segment(segmentation_id: str, value: str | None, names: dict[tuple[str, str], str]) -> dict[str, Any]:
    name = names.get((segmentation_id, str(value)))
    return {
        "segmentation_id": segmentation_id,
        "segment": value,
        "segment_name": name,
        "label": segment_label(segmentation_id, value, name),
        "config_entry": f"{segmentation_id}__{value}",
    }


def validate_segment_entries(entries: list[str], catalog: list[dict[str, Any]]) -> list[str]:
    """Errors for `segments` entries that do not exist in the catalogue, with did-you-mean suggestions."""
    errors: list[str] = []
    by_id = {doc["segmentation_id"]: doc for doc in catalog}
    for entry in entries:
        segmentation_id, sep, value = entry.partition("__")
        if not (sep and segmentation_id and value):
            errors.append(f"Malformed entry '{entry}': expected '{{segmentation_id}}__{{segment_value}}'")
            continue
        doc = by_id.get(segmentation_id)
        if doc is None:
            case_match = next((d for d in catalog if d["segmentation_id"].lower() == segmentation_id.lower()), None)
            if case_match:
                errors.append(
                    f"Unknown segmentation_id '{segmentation_id}' in '{entry}'. Did you mean "
                    f"'{case_match['segmentation_id']}__{value}'? (segmentation_id is case-sensitive)"
                )
            else:
                errors.append(f"Unknown segmentation_id '{segmentation_id}' in '{entry}'. Available: {sorted(by_id)}")
            continue
        values = {segment.get("value") for segment in doc.get("segments", [])}
        if value in values:
            continue
        needle = value.lower()
        suggestions: list[str] = []
        for candidate in catalog:
            for segment in candidate.get("segments", []):
                seg_value = segment.get("value") or ""
                seg_name = segment.get("name") or ""
                if needle in seg_value.lower() or needle in seg_name.lower():
                    suggestion = f"{candidate['segmentation_id']}__{seg_value}" + (
                        f" (name: {seg_name})" if seg_name else ""
                    )
                    if suggestion not in suggestions:
                        suggestions.append(suggestion)
        if suggestions:
            errors.append(
                f"Segment value '{value}' not found in segmentation '{segmentation_id}' for entry '{entry}'. "
                f"Did you mean: {suggestions[:5]}"
            )
        else:
            errors.append(
                f"Segment value '{value}' not found in segmentation '{segmentation_id}' for entry '{entry}'. "
                f"Valid values: {sorted(v for v in values if v)}"
            )
    return errors
