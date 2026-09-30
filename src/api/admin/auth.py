"""Admin API authentication: one shared Bearer token, the same for every brand.

cadmin stores it as the service's secret key and sends `Authorization: Bearer <key>` on every call.
"""

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from settings import settings
from storage.mongo import MongoStore

security = HTTPBearer()


async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    if not settings.ADMIN_API_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if credentials.credentials != settings.ADMIN_API_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return credentials.credentials


def get_store(request: Request) -> MongoStore:
    """The store the application was started with (or the one a test installed)."""
    return request.app.state.store


def require_brand(x_brand: str | None) -> str:
    """Validate the `X-Brand` header against the configured brands. Required by every per-brand resource."""
    brand = (x_brand or "").strip().upper()
    if not brand:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-Brand header is required")
    if brand not in settings.BRANDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown brand '{brand}'; configured brands: {settings.BRANDS}",
        )
    return brand
