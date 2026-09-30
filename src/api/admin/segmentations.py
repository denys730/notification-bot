"""Segmentations and custom-segment CSV imports: `/api/admin/segmentations/*`.

The catalogue a checker's `segments` gate is validated against, in the shapes cadmin's picker and
"Custom segments" page read. A custom segmentation (`product == "custom"`) is built wholesale from
a CSV with `player_id` and `segment` columns; the others are seeded and read-only.
"""

import csv
import io
import logging
import re
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.admin.auth import get_store, require_brand, verify_admin_token
from constants import CUSTOM_SEGMENTATION_PRODUCT
from storage.mongo import MongoStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/segmentations", tags=["admin"], dependencies=[Depends(verify_admin_token)])

RESERVED_COLUMNS = {"player_id", "segment", "is_test"}


# ---- schemas --------------------------------------------------------------------------------------


class SegmentItemSchema(BaseModel):
    value: str
    name: str | None = None
    description: str | None = None


class SegmentationResponse(BaseModel):
    id: str
    segmentation_id: str
    brand: str | None = None
    operator_id: str | None = None
    product: str | None = None
    name: str | None = None
    description: str | None = None
    segments: list[SegmentItemSchema] = Field(default_factory=list)
    segment_count: int | None = None
    created_at: str | None = None


class SegmentationListResponse(BaseModel):
    segmentations: list[SegmentationResponse]
    meta: dict[str, Any] = Field(default_factory=dict)


class SegmentationSegmentsResponse(BaseModel):
    segments: list[SegmentItemSchema]
    total: int


class SegmentResolveRequest(BaseModel):
    keys: list[str] = Field(default_factory=list)


class SegmentLabelItem(BaseModel):
    key: str
    label: str
    segmentation_name: str | None = None
    segment_name: str | None = None


class SegmentResolveResponse(BaseModel):
    items: list[SegmentLabelItem]
    segmentations: list[SegmentationResponse] = Field(default_factory=list)


class SegmentationImportRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None
    csv: str = Field(..., min_length=1)


class SegmentationImportResponse(BaseModel):
    segmentation_id: str
    name: str
    product: str
    segments_created: int
    player_segments_created: int
    profiles_metadata_updated: int
    players_without_profile: int
    rows_total: int
    skipped_test: int
    skipped_invalid: int


class SegmentationPlayersImportRequest(BaseModel):
    csv: str = Field(..., min_length=1)


class SegmentationPlayersImportResponse(SegmentationImportResponse):
    segments_added: int = 0


class SegmentationDeleteResponse(BaseModel):
    segmentation_id: str
    deleted_player_segments: int


class SegmentationPlayerItem(BaseModel):
    player_id: str
    segment: str
    segment_name: str | None = None
    valid_from: str | None = None
    created_at: str | None = None


class SegmentationPlayersResponse(BaseModel):
    segmentation: SegmentationResponse
    players: list[SegmentationPlayerItem]
    meta: dict[str, Any] = Field(default_factory=dict)


class SegmentationPlayerRemoveResponse(BaseModel):
    segmentation_id: str
    player_id: str
    deleted_player_segments: int


# ---- helpers --------------------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def segmentation_response(doc: dict[str, Any], *, with_segments: bool) -> SegmentationResponse:
    segments = doc.get("segments") or []
    return SegmentationResponse(
        id=str(doc.get("_id")),
        segmentation_id=doc.get("segmentation_id", ""),
        brand=doc.get("brand"),
        operator_id=doc.get("operator_id"),
        product=doc.get("product"),
        name=doc.get("name"),
        description=doc.get("description"),
        segments=[SegmentItemSchema(**item) for item in segments] if with_segments else [],
        segment_count=len(segments),
        created_at=_iso(doc.get("created_at")),
    )


def parse_object_id(seg_id: str) -> ObjectId:
    try:
        return ObjectId(seg_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segmentation not found")


async def find_segmentation(store: MongoStore, brand: str, seg_id: str) -> dict[str, Any]:
    """By Mongo id first, then by `segmentation_id` — cadmin addresses rows by the former, links by the latter."""
    doc = None
    if len(seg_id) == 24:
        try:
            doc = await store.segmentations(brand).find_one({"_id": ObjectId(seg_id)})
        except Exception:
            doc = None
    if doc is None:
        doc = await store.segmentations(brand).find_one({"segmentation_id": seg_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segmentation not found")
    return doc


def require_custom(doc: dict[str, Any]) -> None:
    if doc.get("product") != CUSTOM_SEGMENTATION_PRODUCT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only custom segmentations (product='custom') can be modified",
        )


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "t"}


class ParsedCsv:
    def __init__(self) -> None:
        self.rows_total = 0
        self.skipped_test = 0
        self.skipped_invalid = 0
        self.segments: list[tuple[str, str]] = []  # (name, value) in first-seen order
        self.name_to_value: dict[str, str] = {}
        self.assignments: list[tuple[str, str]] = []  # (player_id, value)


def parse_segments_csv(csv_text: str, existing: dict[str, str], next_value: int) -> ParsedCsv:
    """Rows with a truthy `is_test` are skipped; rows missing `player_id` or `segment` are skipped.
    New segment names are numbered from `next_value` in first-seen order."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [name.strip() for name in (reader.fieldnames or [])]
    missing = [column for column in ("player_id", "segment") if column not in fieldnames]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CSV is missing columns: {missing}")
    parsed = ParsedCsv()
    parsed.name_to_value = dict(existing)
    for row in reader:
        parsed.rows_total += 1
        row = {(key or "").strip(): value for key, value in row.items()}
        if _is_truthy(row.get("is_test")):
            parsed.skipped_test += 1
            continue
        player_id = (row.get("player_id") or "").strip()
        segment_name = (row.get("segment") or "").strip()
        if not player_id or not segment_name:
            parsed.skipped_invalid += 1
            continue
        if segment_name not in parsed.name_to_value:
            parsed.name_to_value[segment_name] = str(next_value)
            parsed.segments.append((segment_name, str(next_value)))
            next_value += 1
        parsed.assignments.append((player_id, parsed.name_to_value[segment_name]))
    if not parsed.assignments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid rows found (every row was a test row or missing player_id/segment)",
        )
    return parsed


async def write_assignments(store: MongoStore, brand: str, segmentation: dict[str, Any], parsed: ParsedCsv) -> int:
    now = datetime.now(UTC)
    collection = store.player_segments(brand)
    created = 0
    seen: set[tuple[str, str]] = set()
    for player_id, value in parsed.assignments:
        if (player_id, value) in seen:
            continue
        seen.add((player_id, value))
        exists = await collection.find_one(
            {"segmentation_id": segmentation["segmentation_id"], "player_id": player_id, "segment": value}
        )
        if exists:
            continue
        await collection.insert_one(
            {
                "brand": brand,
                "player_id": player_id,
                "segmentation_id": segmentation["segmentation_id"],
                "segment": value,
                "product": CUSTOM_SEGMENTATION_PRODUCT,
                "action": "add",
                "valid_from": now,
                "valid_to": None,
                "timestamp": now,
                "created_at": now,
            }
        )
        created += 1
    return created


# ---- routes ---------------------------------------------------------------------------------------


@router.post(
    "/import",
    response_model=SegmentationImportResponse,
    status_code=HTTPStatus.OK,
    summary="Import custom segmentation",
)
async def import_custom_segmentation(
    request: SegmentationImportRequest,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationImportResponse:
    brand = require_brand(x_brand)
    parsed = parse_segments_csv(request.csv, existing={}, next_value=1)
    now = datetime.now(UTC)
    segmentation = {
        "segmentation_id": uuid.uuid4().hex,
        "brand": brand,
        "operator_id": None,
        "product": CUSTOM_SEGMENTATION_PRODUCT,
        "name": request.name.strip(),
        "description": request.description,
        "segments": [{"value": value, "name": name, "description": None} for name, value in parsed.segments],
        "created_at": now,
    }
    await store.segmentations(brand).insert_one(segmentation)
    created = await write_assignments(store, brand, segmentation, parsed)
    return SegmentationImportResponse(
        segmentation_id=segmentation["segmentation_id"],
        name=segmentation["name"],
        product=CUSTOM_SEGMENTATION_PRODUCT,
        segments_created=len(parsed.segments),
        player_segments_created=created,
        profiles_metadata_updated=0,
        players_without_profile=0,
        rows_total=parsed.rows_total,
        skipped_test=parsed.skipped_test,
        skipped_invalid=parsed.skipped_invalid,
    )


@router.get("", response_model=SegmentationListResponse, status_code=HTTPStatus.OK, summary="List segmentations")
async def list_segmentations(
    product: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationListResponse:
    brand = require_brand(x_brand)
    query: dict[str, Any] = {}
    if product:
        query["product"] = product
    if q and q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": pattern}, {"description": pattern}, {"segmentation_id": pattern}]
    docs = await store.segmentations(brand).find(query).sort([("created_at", -1), ("_id", -1)]).to_list(length=None)
    total = len(docs)
    start = (page - 1) * per_page
    return SegmentationListResponse(
        segmentations=[segmentation_response(doc, with_segments=False) for doc in docs[start : start + per_page]],
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.get("/{seg_id}/segments", response_model=SegmentationSegmentsResponse, status_code=HTTPStatus.OK)
async def list_segmentation_segments(
    seg_id: str,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=1000),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationSegmentsResponse:
    brand = require_brand(x_brand)
    doc = await find_segmentation(store, brand, seg_id)
    items = doc.get("segments") or []
    if q and q.strip():
        needle = q.strip().lower()
        items = [
            s for s in items if needle in (s.get("value") or "").lower() or needle in (s.get("name") or "").lower()
        ]
    start = (page - 1) * per_page
    return SegmentationSegmentsResponse(
        segments=[SegmentItemSchema(**item) for item in items[start : start + per_page]], total=len(items)
    )


@router.post("/resolve", response_model=SegmentResolveResponse, status_code=HTTPStatus.OK)
async def resolve_segment_labels(
    request: SegmentResolveRequest,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentResolveResponse:
    brand = require_brand(x_brand)
    wanted_ids = {key.partition("__")[0] for key in request.keys if "__" in key}
    docs = await store.segmentations(brand).find({"segmentation_id": {"$in": sorted(wanted_ids)}}).to_list(length=None)
    by_id = {doc["segmentation_id"]: doc for doc in docs}
    items: list[SegmentLabelItem] = []
    used: dict[str, dict[str, Any]] = {}
    for key in request.keys:
        segmentation_id, sep, value = key.partition("__")
        doc = by_id.get(segmentation_id) if sep else None
        segment = next((s for s in (doc or {}).get("segments", []) if s.get("value") == value), None) if doc else None
        if doc is None or segment is None:
            items.append(SegmentLabelItem(key=key, label=key))
            continue
        used[segmentation_id] = doc
        seg_name = doc.get("name") or segmentation_id
        value_name = segment.get("name") or value
        items.append(
            SegmentLabelItem(
                key=key, label=f"{seg_name} › {value_name}", segmentation_name=seg_name, segment_name=value_name
            )
        )
    return SegmentResolveResponse(
        items=items,
        segmentations=[segmentation_response(doc, with_segments=False) for doc in used.values()],
    )


@router.get("/{seg_id}/players", response_model=SegmentationPlayersResponse, status_code=HTTPStatus.OK)
async def list_segmentation_players(
    seg_id: str,
    q: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationPlayersResponse:
    brand = require_brand(x_brand)
    doc = await find_segmentation(store, brand, seg_id)
    query: dict[str, Any] = {"segmentation_id": doc["segmentation_id"], "action": {"$ne": "remove"}}
    if q and q.strip():
        query["player_id"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    if segment:
        query["segment"] = segment
    rows = await store.player_segments(brand).find(query).sort([("created_at", -1), ("_id", -1)]).to_list(length=None)
    names = {s.get("value"): s.get("name") for s in doc.get("segments") or []}
    start = (page - 1) * per_page
    return SegmentationPlayersResponse(
        segmentation=segmentation_response(doc, with_segments=True),
        players=[
            SegmentationPlayerItem(
                player_id=row.get("player_id", ""),
                segment=row.get("segment", ""),
                segment_name=names.get(row.get("segment"), row.get("segment")),
                valid_from=_iso(row.get("valid_from")),
                created_at=_iso(row.get("created_at")),
            )
            for row in rows[start : start + per_page]
        ],
        meta={"total": len(rows), "page": page, "per_page": per_page},
    )


@router.post("/{seg_id}/players/import", response_model=SegmentationPlayersImportResponse, status_code=HTTPStatus.OK)
async def append_segmentation_players(
    seg_id: str,
    request: SegmentationPlayersImportRequest,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationPlayersImportResponse:
    brand = require_brand(x_brand)
    doc = await find_segmentation(store, brand, seg_id)
    require_custom(doc)
    existing = {s["name"]: s["value"] for s in doc.get("segments") or [] if s.get("name")}
    numeric = [int(s["value"]) for s in doc.get("segments") or [] if str(s.get("value", "")).isdigit()]
    parsed = parse_segments_csv(request.csv, existing=existing, next_value=(max(numeric) + 1) if numeric else 1)
    if parsed.segments:
        doc["segments"] = list(doc.get("segments") or []) + [
            {"value": value, "name": name, "description": None} for name, value in parsed.segments
        ]
        await store.segmentations(brand).update_one({"_id": doc["_id"]}, {"$set": {"segments": doc["segments"]}})
    created = await write_assignments(store, brand, doc, parsed)
    return SegmentationPlayersImportResponse(
        segmentation_id=doc["segmentation_id"],
        name=doc.get("name") or "",
        product=CUSTOM_SEGMENTATION_PRODUCT,
        segments_created=len(parsed.segments),
        segments_added=len(parsed.segments),
        player_segments_created=created,
        profiles_metadata_updated=0,
        players_without_profile=0,
        rows_total=parsed.rows_total,
        skipped_test=parsed.skipped_test,
        skipped_invalid=parsed.skipped_invalid,
    )


@router.delete("/{seg_id}/players/{player_id}/", response_model=SegmentationPlayerRemoveResponse)
async def remove_segmentation_player(
    seg_id: str,
    player_id: str,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationPlayerRemoveResponse:
    brand = require_brand(x_brand)
    doc = await find_segmentation(store, brand, seg_id)
    require_custom(doc)
    result = await store.player_segments(brand).delete_many(
        {"segmentation_id": doc["segmentation_id"], "player_id": player_id}
    )
    return SegmentationPlayerRemoveResponse(
        segmentation_id=doc["segmentation_id"], player_id=player_id, deleted_player_segments=result.deleted_count
    )


@router.delete("/{seg_id}/", response_model=SegmentationDeleteResponse, status_code=HTTPStatus.OK)
async def delete_segmentation(
    seg_id: str,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> SegmentationDeleteResponse:
    brand = require_brand(x_brand)
    doc = await find_segmentation(store, brand, seg_id)
    require_custom(doc)
    result = await store.player_segments(brand).delete_many({"segmentation_id": doc["segmentation_id"]})
    await store.segmentations(brand).delete_one({"_id": doc["_id"]})
    return SegmentationDeleteResponse(
        segmentation_id=doc["segmentation_id"], deleted_player_segments=result.deleted_count
    )
