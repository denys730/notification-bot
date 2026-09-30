"""Admin API for checker rows — the surface cadmin's Alert Bot proxy talks to.

Paths, envelopes, query language and status codes are what that proxy expects:

    GET    /api/admin/checkers?filter=<b64 json>&page=&per_page=&sort[]=&include[]=&exclude[]=
    GET    /api/admin/checkers/codes
    GET    /api/admin/checkers/{id}/
    POST   /api/admin/checkers/            {"checker": {...}} | {"checkers": [...]}
    PATCH  /api/admin/checkers/{id}/       flat body, replaces every field it names
    DELETE /api/admin/checkers/{id}/

Rows carry `brand` in upper case, and every read is scoped by the `X-Brand` header.
"""

import logging
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from api.admin.auth import get_store, verify_admin_token
from api.admin.filters import build_mongo_query, build_sort, decode_filter, parse_boolean
from checkers import checker_for_code
from constants import CheckerCodes
from storage.mongo import MongoStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/checkers", tags=["admin"], dependencies=[Depends(verify_admin_token)])


# ---- schemas --------------------------------------------------------------------------------------


class CheckerResponse(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    brand: str | None = None
    channel: str | None = None
    checker_code: str | None = None
    checker_name: str | None = None
    config: dict[str, Any] | None = None
    description: str | None = None
    enabled: bool | None = None
    frequency_minutes: int | None = None
    cron: str | None = Field(None, description="UTC cron expression; overrides frequency_minutes when set")
    max_instances: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    segments: list[str] | None = Field(None, description="Segment gate: '{segmentation_id}__{segment}' values")
    regions: list[str] | None = Field(None, description="Region gate: registration regions")
    channels: list[str] | None = Field(None, description="Slack channels; derived from `channel` for older rows")


class CheckerCreate(BaseModel):
    brand: str
    channel: str
    channels: list[str] | None = None
    checker_code: str
    checker_name: str
    config: dict[str, Any] | None = None
    description: str | None = None
    enabled: bool = True
    frequency_minutes: int
    cron: str | None = None
    max_instances: int
    segments: list[str] | None = None
    regions: list[str] | None = None


class CheckerUpdate(BaseModel):
    brand: str | None = None
    channel: str | None = None
    channels: list[str] | None = None
    checker_code: str | None = None
    checker_name: str | None = None
    config: dict[str, Any] | None = None
    description: str | None = None
    enabled: bool | None = None
    frequency_minutes: int | None = None
    cron: str | None = None
    max_instances: int | None = None
    segments: list[str] | None = None
    regions: list[str] | None = None


class CheckerListResponse(BaseModel):
    checkers: list[CheckerResponse]
    meta: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class CheckerSingleResponse(BaseModel):
    checker: CheckerResponse
    warnings: list[str] = Field(default_factory=list)


class CheckerCodeItem(BaseModel):
    code: str
    name: str


class CheckerCodesResponse(BaseModel):
    codes: list[CheckerCodeItem]


class CheckerCreateRequest(BaseModel):
    checker: CheckerCreate


class CheckerBulkCreateRequest(BaseModel):
    checkers: list[CheckerCreate]


# ---- serialisation ---------------------------------------------------------------------------------


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat().replace("+00:00", "Z")


def checker_to_dict(doc: dict[str, Any]) -> dict[str, Any]:
    channel = doc.get("channel") or ""
    return {
        "id": str(doc.get("_id", "")),
        "brand": doc.get("brand", ""),
        "channel": channel,
        "checker_code": str(doc.get("checker_code") or ""),
        "checker_name": doc.get("checker_name", ""),
        "config": doc.get("config") or {},
        "description": doc.get("description"),
        "enabled": doc.get("enabled", True),
        "frequency_minutes": doc.get("frequency_minutes", 0),
        "cron": doc.get("cron"),
        "max_instances": doc.get("max_instances", 1),
        "created_at": format_datetime(doc.get("created_at")),
        "updated_at": format_datetime(doc.get("updated_at")),
        "segments": doc.get("segments"),
        "regions": doc.get("regions"),
        "channels": doc.get("channels") or ([channel] if channel else []),
    }


def project_fields(rows: list[dict[str, Any]], include: list[str], exclude: list[str]) -> list[dict[str, Any]]:
    """`include[]` / `exclude[]` projection. `id` always survives; `exclude[]=*` keeps only `include[]`."""
    if not include and not exclude:
        return rows
    if "*" in exclude:
        keep = set(include) | {"id"}
        return [{key: value for key, value in row.items() if key in keep} for row in rows]
    keep = (set(include) | {"id"}) if include else None
    dropped = set(exclude)
    return [
        {key: value for key, value in row.items() if (keep is None or key in keep) and key not in dropped}
        for row in rows
    ]


# ---- validation -----------------------------------------------------------------------------------


def validation_error(field: str, problems: list[str]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "Validation error", "details": {field: problems}},
    )


def validate_checker_code(checker_code: str | None) -> str:
    try:
        return CheckerCodes(checker_code).value
    except ValueError:
        raise validation_error("checker_code", [f"Invalid checker_code: {checker_code}"])


def _describe_range(minimum: float | None, maximum: float | None) -> str:
    if minimum is not None and maximum is not None:
        return f"{minimum} to {maximum}"
    if minimum is not None:
        return f"at least {minimum}"
    return f"at most {maximum}"


def validate_checker_config(checker_code: str | None, config: dict[str, Any] | None) -> None:
    """Reject a `config` that omits a required knob or puts a bounded one outside its range.

    A supplied `config` replaces the stored one in full, so an object omitting a knob deletes it.
    A request carrying no `config` cannot lose a knob and is not validated — which is also what keeps
    a row that is already incomplete editable, and therefore repairable.
    """
    if config is None:
        return
    checker_cls = checker_for_code(checker_code)
    if checker_cls is None:
        return
    problems: list[str] = []
    missing = sorted(checker_cls.REQUIRED_CONFIG_KEYS - set(config))
    if missing:
        problems.append(
            f"Missing required keys for {checker_code}: {', '.join(missing)}. The config object replaces the "
            f"stored one in full, so it must carry every knob the checker reads without a default."
        )
    for knob, (minimum, maximum) in sorted(checker_cls.CONFIG_VALUE_BOUNDS.items()):
        if knob not in config:
            continue
        try:
            value = float(config[knob])
        except (TypeError, ValueError):
            continue
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            problem = (
                f"{knob} is outside its admissible range for {checker_code}: {config[knob]} is not "
                f"{_describe_range(minimum, maximum)}."
            )
            reason = checker_cls.CONFIG_BOUND_REASONS.get(knob)
            problems.append(f"{problem} {reason}" if reason else problem)
    if problems:
        raise validation_error("config", problems)


def checker_config_warnings(checker_code: str | None, config: dict[str, Any] | None) -> list[str]:
    if config is None:
        return []
    checker_cls = checker_for_code(checker_code)
    if checker_cls is None:
        return []
    try:
        return [str(message) for message in checker_cls.config_warnings(config)]
    except Exception as error:  # advice must never cost a write that was otherwise accepted
        logger.warning("config_warnings hook of %s raised: %s", checker_cls.__name__, error)
        return []


def parse_object_id(checker_id: str) -> ObjectId:
    try:
        return ObjectId(checker_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checker not found")


# ---- routes ---------------------------------------------------------------------------------------


@router.get("", response_model=CheckerListResponse, status_code=HTTPStatus.OK, summary="List Checkers")
async def list_checkers(
    filter: str | None = Query(None, description="Base64-encoded JSON filter"),
    sort: list[str] = Query(default=[], alias="sort[]"),
    per_page: int = Query(50, ge=1, le=1000),
    page: int = Query(1, ge=1),
    exclude_count: str | bool = Query(False),
    include: list[str] = Query(default=[], alias="include[]"),
    exclude: list[str] = Query(default=[], alias="exclude[]"),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> CheckerListResponse:
    query: dict[str, Any] = {}
    if filter:
        query.update(build_mongo_query(decode_filter(filter)))
    query["brand"] = (x_brand or "").upper()

    total_results = 0 if parse_boolean(exclude_count) else await store.checkers.count_documents(query)
    cursor = store.checkers.find(query)
    if sort:
        cursor = cursor.sort(build_sort(sort))
    docs = await cursor.skip((page - 1) * per_page).limit(per_page).to_list(length=per_page)
    rows = project_fields([checker_to_dict(doc) for doc in docs], include, exclude)
    total_pages = (total_results + per_page - 1) // per_page if total_results > 0 else 0
    return CheckerListResponse(
        checkers=[CheckerResponse.model_validate(row) for row in rows],
        meta={"total_results": total_results, "per_page": per_page, "page": page, "total_pages": total_pages},
    )


@router.get("/codes", response_model=CheckerCodesResponse, status_code=HTTPStatus.OK, summary="List Checker Codes")
async def list_checker_codes(x_brand: str | None = Header(default=None, alias="X-Brand")) -> CheckerCodesResponse:
    """Brand-independent; `X-Brand` is accepted for consistency and ignored."""
    return CheckerCodesResponse(
        codes=[CheckerCodeItem(code=code.value, name=code.value.replace("_", " ").title()) for code in CheckerCodes]
    )


@router.get(
    "/{checker_id}/", response_model=CheckerSingleResponse, status_code=HTTPStatus.OK, summary="Get Single Checker"
)
async def get_checker(
    checker_id: str,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> CheckerSingleResponse:
    doc = await store.checkers.find_one({"_id": parse_object_id(checker_id)})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checker not found")
    return CheckerSingleResponse(checker=CheckerResponse.model_validate(checker_to_dict(doc)))


async def _insert_checker(store: MongoStore, data: CheckerCreate) -> dict[str, Any]:
    code = validate_checker_code(data.checker_code)
    validate_checker_config(code, data.config)
    doc: dict[str, Any] = {
        "brand": data.brand.strip().upper(),
        "channel": data.channel,
        "channels": data.channels,
        "checker_code": code,
        "checker_name": data.checker_name,
        "config": data.config or {},
        "description": data.description,
        "enabled": data.enabled,
        "frequency_minutes": data.frequency_minutes,
        "cron": data.cron,
        "max_instances": data.max_instances,
        "segments": data.segments,
        "regions": data.regions,
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    try:
        result = await store.checkers.insert_one(doc)
    except DuplicateKeyError:
        raise validation_error(
            "checker_name", [f"A checker named '{data.checker_name}' already exists for brand '{doc['brand']}'"]
        )
    doc["_id"] = result.inserted_id
    return doc


@router.post("/", status_code=HTTPStatus.CREATED, summary="Create Checker")
async def create_checker(
    http_request: Request,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> CheckerSingleResponse | CheckerListResponse:
    body = await http_request.json()
    if "checkers" in body:
        request = CheckerBulkCreateRequest(**body)
        created: list[CheckerResponse] = []
        warnings: list[str] = []
        errors: list[dict[str, Any]] = []
        for index, data in enumerate(request.checkers):
            try:
                doc = await _insert_checker(store, data)
            except HTTPException as error:
                errors.append({f"checker_{index}": error.detail})
                continue
            created.append(CheckerResponse.model_validate(checker_to_dict(doc)))
            warnings.extend(
                f"{doc['checker_name']}: {message}"
                for message in checker_config_warnings(doc["checker_code"], doc["config"])
            )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "Validation error", "details": errors}
            )
        return CheckerListResponse(
            checkers=created,
            meta={"total_results": len(created), "per_page": len(created), "page": 1, "total_pages": 1},
            warnings=warnings,
        )
    if "checker" in body:
        request_single = CheckerCreateRequest(**body)
        doc = await _insert_checker(store, request_single.checker)
        return CheckerSingleResponse(
            checker=CheckerResponse.model_validate(checker_to_dict(doc)),
            warnings=checker_config_warnings(doc["checker_code"], doc["config"]),
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "Invalid request body. Expected 'checker' or 'checkers' key."},
    )


UPDATABLE_FIELDS = {
    "brand",
    "channel",
    "channels",
    "checker_name",
    "config",
    "description",
    "enabled",
    "frequency_minutes",
    "cron",
    "max_instances",
    "segments",
    "regions",
}


@router.patch(
    "/{checker_id}/", response_model=CheckerSingleResponse, status_code=HTTPStatus.OK, summary="Update Checker"
)
async def update_checker(
    checker_id: str,
    request: CheckerUpdate,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> CheckerSingleResponse:
    object_id = parse_object_id(checker_id)
    doc = await store.checkers.find_one({"_id": object_id, "brand": (x_brand or "").upper()})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checker not found")

    update = request.model_dump(exclude_unset=True)
    effective_code = (
        validate_checker_code(update["checker_code"]) if update.get("checker_code") else doc.get("checker_code")
    )
    # Before the first mutation: a rejected request leaves the row exactly as it was.
    if "config" in update:
        validate_checker_config(effective_code, update["config"])
    if update.get("checker_code"):
        doc["checker_code"] = effective_code
    for field_name in UPDATABLE_FIELDS:
        if field_name in update:
            doc[field_name] = update[field_name]
    if "brand" in update and update["brand"]:
        doc["brand"] = str(update["brand"]).strip().upper()
    # A client that only knows `channel` must still be able to re-route the row.
    if "channel" in update and "channels" not in update:
        value = (update["channel"] or "").strip()
        doc["channels"] = [value] if value else None
    doc["updated_at"] = datetime.now(UTC)
    try:
        await store.checkers.replace_one({"_id": object_id}, doc)
    except DuplicateKeyError:
        raise validation_error(
            "checker_name", [f"A checker named '{doc['checker_name']}' already exists for brand '{doc['brand']}'"]
        )
    return CheckerSingleResponse(
        checker=CheckerResponse.model_validate(checker_to_dict(doc)),
        warnings=checker_config_warnings(doc.get("checker_code"), doc.get("config")),
    )


@router.delete("/{checker_id}/", status_code=HTTPStatus.NO_CONTENT, summary="Delete Checker")
async def delete_checker(
    checker_id: str,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> Response:
    """Deletes the row, so a review link's `delete` change has a visible effect. The proxy tolerates a
    404 on a repeated delete, which is what it gets."""
    await store.checkers.delete_one({"_id": parse_object_id(checker_id), "brand": (x_brand or "").upper()})
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.delete("/", status_code=HTTPStatus.NO_CONTENT, summary="Bulk Delete Checkers")
async def bulk_delete_checkers(
    filter: str = Query(..., description="Base64-encoded JSON filter"),
    x_brand: str | None = Header(default=None, alias="X-Brand"),
) -> Response:
    """Not supported: answers 204 and deletes nothing."""
    return Response(status_code=HTTPStatus.NO_CONTENT)
