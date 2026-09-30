"""The authenticated caller and the brands cadmin grants them for Alert Bot services.

Over HTTP the principal travels in the SDK's auth context; over stdio the one resolved at startup
is held in a ContextVar. `current_principal` hides which is in play so no tool takes a principal
argument — an argument can be forgotten, and forgetting means serving another team's brand.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


class AccessDenied(Exception):
    """Authenticated, but not entitled to what was asked for."""


@dataclass(frozen=True)
class GrantedService:
    slug: str
    name: str
    brand: str | None


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    is_superuser: bool
    brands: frozenset[str]
    services: tuple[GrantedService, ...] = ()

    def may_read(self, brand: str) -> bool:
        return brand.strip().upper() in self.brands

    def require(self, brand: str) -> None:
        wanted = brand.strip().upper()
        if wanted in self.brands:
            return
        granted = ", ".join(sorted(self.brands)) or "none"
        raise AccessDenied(
            f"No Alert Bot access to brand '{wanted}' for {self.email}. Granted brands: {granted}. "
            f"Access is granted per (brand, service) in cadmin."
        )

    def to_claims(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "is_superuser": self.is_superuser,
            "brands": sorted(self.brands),
            "services": [{"slug": s.slug, "name": s.name, "brand": s.brand} for s in self.services],
        }


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    return Principal(
        user_id=str(claims.get("user_id") or ""),
        email=str(claims.get("email") or ""),
        is_superuser=bool(claims.get("is_superuser")),
        brands=frozenset(claims.get("brands") or ()),
        services=tuple(
            GrantedService(slug=s.get("slug", ""), name=s.get("name", ""), brand=s.get("brand"))
            for s in claims.get("services") or ()
        ),
    )


_stdio_principal: ContextVar[Principal | None] = ContextVar("mcp_stdio_principal", default=None)


def set_principal(principal: Principal | None) -> None:
    _stdio_principal.set(principal)


def current_principal() -> Principal | None:
    from mcp_server.auth.verifier import principal_from_access_token

    return principal_from_access_token() or _stdio_principal.get()
