"""The MCP OAuth seam: a `TokenVerifier` and the `AuthSettings` that switch the flow on.

Given `AuthSettings`, FastMCP serves the protected-resource metadata, answers an unauthenticated
request with the `401` + `WWW-Authenticate` pair that starts the browser flow, and carries the
verified token through the request. Deciding whether a token is real is the one method here.
"""

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from mcp_server import settings
from mcp_server.auth.cadmin import InvalidToken, resolve_principal
from mcp_server.auth.principal import Principal, principal_from_claims


class CadminTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await resolve_principal(token)
        except InvalidToken:
            return None  # "not authenticated": the SDK turns it into the 401 that restarts the flow
        return AccessToken(
            token=token,
            client_id=principal.user_id,
            scopes=[settings.SCOPE_READ],
            subject=principal.email,
            resource=settings.public_url() or None,
            claims=principal.to_claims(),
        )


def auth_settings() -> AuthSettings | None:
    """The OAuth configuration for HTTP, or None (stdio has no HTTP surface to protect)."""
    issuer = settings.cadmin_issuer()
    resource = settings.public_url()
    if not (issuer and resource):
        return None
    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
        required_scopes=[settings.SCOPE_READ],
    )


def principal_from_access_token() -> Principal | None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    access_token = get_access_token()
    if access_token is None:
        return None
    return principal_from_claims(access_token.claims or {})
