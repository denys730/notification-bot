"""Read-only admin API over the per-brand alert journal: `GET /api/admin/alert-journal[/{id}]`.

The journal holds one document per alert event the (demo) bot sent. Nothing here writes it; the
seed fills it so the MCP tools and the cadmin pages have history to show.
"""

from http import HTTPStatus
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.admin.auth import get_store, require_brand, verify_admin_token
from api.admin.checkers import format_datetime
from api.admin.filters import build_mongo_query, build_sort, decode_filter
from storage.mongo import MongoStore

router = APIRouter(prefix="/api/admin/alert-journal", tags=["admin"], dependencies=[Depends(verify_admin_token)])

# Per-event detail that would swamp a listing; `GET /{alert_id}` always carries both.
LIST_EXCLUDED_FIELDS = {"text", "resolved_config"}


class AlertDeliveryResponse(BaseModel):
    transport: str | None = None
    channel: str | None = None
    ok: bool | None = None
    ts: str | None = None
    thread_ts: str | None = None
    error: str | None = None
    text: str | None = None


class AlertJournalResponse(BaseModel):
    id: str
    brand: str | None = None
    checker_code: str | None = None
    checker_name: str | None = None
    run_id: str | None = None
    run_started_at: str | None = None
    status: str | None = None
    correlation_id: str | None = None
    uniq_alert_id: str | None = None
    entity_id: str | None = None
    player_id: str | None = None
    operator_id: str | None = None
    text: str | None = None
    requested_channels: list[str] | None = None
    deliveries: list[AlertDeliveryResponse] | None = None
    is_threaded_reply: bool | None = None
    reply_to: str | None = None
    context: dict[str, Any] | None = None
    resolved_config: dict[str, Any] | None = None
    created_at: str | None = None
    expired_at: str | None = None


class AlertJournalListResponse(BaseModel):
    alert_events: list[AlertJournalResponse]
    meta: dict[str, Any] = Field(default_factory=dict)


class AlertJournalSingleResponse(BaseModel):
    alert_event: AlertJournalResponse


def journal_to_dict(doc: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in doc.items() if key != "_id"}
    out["id"] = str(doc.get("_id", ""))
    for key in ("run_started_at", "created_at", "expired_at"):
        if key in out:
            out[key] = format_datetime(out[key]) if hasattr(out[key], "isoformat") else out[key]
    return out


@router.get("", response_model=AlertJournalListResponse, status_code=HTTPStatus.OK, summary="List alert events")
async def list_alerts(
    filter: str | None = Query(None, description="Base64-encoded JSON filter"),
    sort: list[str] = Query(default=[], alias="sort[]"),
    per_page: int = Query(50, ge=1, le=1000),
    page: int = Query(1, ge=1),
    exclude_count: bool = Query(False),
    include: list[str] = Query(default=[], alias="include[]"),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> AlertJournalListResponse:
    brand = require_brand(x_brand)
    query: dict[str, Any] = {}
    if filter:
        query.update(build_mongo_query(decode_filter(filter)))
    collection = store.alert_journal(brand)
    total_results = 0 if exclude_count else await collection.count_documents(query)
    hidden = {field for field in LIST_EXCLUDED_FIELDS if field not in include}
    cursor = collection.find(query, {field: 0 for field in hidden} or None)
    cursor = cursor.sort(build_sort(sort) if sort else [("created_at", -1)])
    docs = await cursor.skip((page - 1) * per_page).limit(per_page).to_list(length=per_page)
    total_pages = (total_results + per_page - 1) // per_page if total_results > 0 else 0
    return AlertJournalListResponse(
        alert_events=[AlertJournalResponse.model_validate(journal_to_dict(doc)) for doc in docs],
        meta={
            "total_results": total_results,
            "per_page": per_page,
            "page": page,
            "total_pages": total_pages,
            "brand": brand,
        },
    )


@router.get(
    "/{alert_id}", response_model=AlertJournalSingleResponse, status_code=HTTPStatus.OK, summary="Get one alert event"
)
async def get_alert(
    alert_id: str,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> AlertJournalSingleResponse:
    brand = require_brand(x_brand)
    try:
        object_id = ObjectId(alert_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert event not found")
    doc = await store.alert_journal(brand).find_one({"_id": object_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert event not found")
    return AlertJournalSingleResponse(alert_event=AlertJournalResponse.model_validate(journal_to_dict(doc)))
