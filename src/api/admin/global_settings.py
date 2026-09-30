"""Per-brand global settings: `GET`/`PUT /api/admin/settings`, one `{name, value}` document each.

The field set is what the cadmin settings page reads, so it works unchanged. `regions` and
`default_region` back the region gate; the rest are stored and returned as sent.
"""

import logging
import re
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from api.admin.auth import get_store, require_brand, verify_admin_token
from constants import ALWAYS_DEFAULTED_SETTINGS, GLOBAL_SETTINGS_DEFAULTS, GlobalSettingNames
from storage.mongo import MongoStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/settings", tags=["admin"], dependencies=[Depends(verify_admin_token)])

ENTITY_TAGS_REGEX_MAX_LENGTH = 500


class GlobalSettingsResponse(BaseModel):
    min_win_to_store_eur: float | None = None
    business_metrics_max_lag_seconds: float | None = None
    regions: list[str] = []
    default_region: str | None = None
    crypto_address_max_players_to_publish: int = 10
    crypto_address_max_transactions_to_publish: int = 100000
    crypto_address_max_balance_eur_to_publish: float = 1000000
    crypto_address_exclude_entity_tags_regex: str | None = None


class GlobalSettingsUpdateRequest(BaseModel):
    """Partial update — only fields present in the body change."""

    min_win_to_store_eur: float | None = Field(default=None, ge=0)
    business_metrics_max_lag_seconds: float | None = Field(default=None, ge=0)
    regions: list[str] | None = Field(default=None, description="The brand's catalogue of known regions")
    default_region: str | None = Field(default=None, description="Must be one of `regions`; null disables")
    crypto_address_max_players_to_publish: int | None = Field(default=None, ge=0)
    crypto_address_max_transactions_to_publish: int | None = Field(default=None, ge=0)
    crypto_address_max_balance_eur_to_publish: float | None = Field(default=None, ge=0)
    crypto_address_exclude_entity_tags_regex: str | None = None


async def read_all_values(store: MongoStore, brand: str) -> dict[str, Any]:
    values: dict[str, Any] = {name.value: default for name, default in GLOBAL_SETTINGS_DEFAULTS.items()}
    async for doc in store.global_settings(brand).find({}):
        if doc.get("name") in values:
            values[doc["name"]] = doc.get("value")
    for name in ALWAYS_DEFAULTED_SETTINGS:
        if values.get(name.value) is None:
            values[name.value] = GLOBAL_SETTINGS_DEFAULTS[name]
    return values


async def write_value(store: MongoStore, brand: str, name: GlobalSettingNames, value: Any) -> None:
    await store.global_settings(brand).update_one({"name": name.value}, {"$set": {"value": value}}, upsert=True)


def _validate_default_region(updates: dict[str, Any], current: dict[str, Any]) -> None:
    """The fallback only means something as a member of the catalogue the request leaves behind."""
    if "regions" not in updates and "default_region" not in updates:
        return
    catalogue = updates.get("regions") if "regions" in updates else current.get("regions")
    default = updates.get("default_region") if "default_region" in updates else current.get("default_region")
    if not default:
        return
    known = {str(r).strip().upper() for r in (catalogue or []) if str(r).strip()}
    if default.strip().upper() not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"default_region '{default}' is not in the regions catalogue {sorted(known)}",
        )


def _validate_entity_tags_regex(updates: dict[str, Any]) -> None:
    pattern = updates.get("crypto_address_exclude_entity_tags_regex")
    if pattern is None:
        return
    if len(pattern) > ENTITY_TAGS_REGEX_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"crypto_address_exclude_entity_tags_regex exceeds {ENTITY_TAGS_REGEX_MAX_LENGTH} characters",
        )
    try:
        re.compile(pattern)
    except re.error as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"crypto_address_exclude_entity_tags_regex is not a valid regular expression: {error}",
        ) from error


@router.get("", response_model=GlobalSettingsResponse, status_code=HTTPStatus.OK, summary="Get global settings")
async def get_global_settings(
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> GlobalSettingsResponse:
    brand = require_brand(x_brand)
    return GlobalSettingsResponse(**await read_all_values(store, brand))


@router.put("", response_model=GlobalSettingsResponse, status_code=HTTPStatus.OK, summary="Update global settings")
async def update_global_settings(
    request: GlobalSettingsUpdateRequest,
    x_brand: str | None = Header(default=None, alias="X-Brand"),
    store: MongoStore = Depends(get_store),
) -> GlobalSettingsResponse:
    brand = require_brand(x_brand)
    updates = request.model_dump(exclude_unset=True)
    current = await read_all_values(store, brand)
    _validate_default_region(updates, current)
    _validate_entity_tags_regex(updates)
    for field_name, value in updates.items():
        await write_value(store, brand, GlobalSettingNames(field_name), value)
    return GlobalSettingsResponse(**await read_all_values(store, brand))
