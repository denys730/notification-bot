"""Resolving a cadmin access token into a principal: `GET /auth/me` + `GET /services`, both scoped to the bearer.

Only cadmin services of type `alert-bot` (its Alert Bot type) grant a brand. `/auth/me` runs on every call (it is what makes the
token real); the grant list is cached per USER for a short TTL, never keyed by the token itself.
"""

import time
from typing import Any

import httpx

from mcp_server import settings
from mcp_server.auth.principal import GrantedService, Principal

ALERT_BOT_SERVICE_TYPE = "alert-bot"
DEFAULT_TIMEOUT_SECONDS = 10.0


class CadminUnavailable(Exception):
    """cadmin could not be reached or answered with an error. Never means 'access granted'."""


class InvalidToken(Exception):
    """cadmin rejected the token."""


_grants_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_cache() -> None:
    _grants_cache.clear()


def principal_from(me: dict[str, Any], services: list[dict[str, Any]]) -> Principal:
    granted: list[GrantedService] = []
    brands: set[str] = set()
    for service in services:
        if service.get("type") != ALERT_BOT_SERVICE_TYPE:
            continue
        brand = service.get("brand_id")
        granted.append(
            GrantedService(
                slug=str(service.get("slug") or service.get("id") or ""),
                name=str(service.get("name") or ""),
                brand=str(brand).strip().upper() if brand else None,
            )
        )
        if brand:
            brands.add(str(brand).strip().upper())
    return Principal(
        user_id=str(me.get("id") or me.get("user_id") or ""),
        email=str(me.get("email") or ""),
        is_superuser=bool(me.get("is_superuser")),
        brands=frozenset(brands),
        services=tuple(granted),
    )


async def resolve_principal(token: str) -> Principal:
    base = settings.cadmin_base_url()
    if not base:
        raise CadminUnavailable("ALERTS_MCP_CADMIN_BASE_URL is not set — the server cannot resolve permissions.")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            me_response = await client.get(f"{base}/auth/me", headers=headers)
            if me_response.status_code in (401, 403):
                raise InvalidToken("cadmin rejected the access token")
            me_response.raise_for_status()
            me = me_response.json()
            user_id = str(me.get("id") or me.get("user_id") or "")
            services = _cached_grants(user_id)
            if services is None:
                services_response = await client.get(f"{base}/services", headers=headers)
                services_response.raise_for_status()
                services = services_response.json()
                _cache_grants(user_id, services)
    except InvalidToken:
        raise
    except httpx.HTTPError as error:
        raise CadminUnavailable(f"Could not reach cadmin at {base}: {error}") from error
    return principal_from(me, services)


def _cached_grants(user_id: str) -> list[dict[str, Any]] | None:
    entry = _grants_cache.get(user_id)
    if entry is None or time.monotonic() >= entry[0]:
        return None
    return entry[1]


def _cache_grants(user_id: str, services: list[dict[str, Any]]) -> None:
    ttl = settings.principal_ttl_seconds()
    if ttl and user_id:
        _grants_cache[user_id] = (time.monotonic() + ttl, services)
