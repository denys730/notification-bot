"""The FastMCP instance every tool, resource and prompt registers against."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import settings
from mcp_server.auth.verifier import CadminTokenVerifier, auth_settings
from mcp_server.content.catalogue import INSTRUCTIONS

# This server performs no writes — the guard test asserts on it.
READ_ONLY = True

READ_ONLY_TOOL = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@dataclass
class ServerContext:
    discovery: dict


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[ServerContext]:
    """Make sure the brands have been read before anything serves a request. Idempotent: with
    `stateless_http` the SDK runs this per client session, not once per process."""
    from mcp_server.storage import ensure_discovered

    report = await ensure_discovered()
    if report is not None:
        log_discovery(report)
    yield ServerContext(discovery=report or {})


def log_discovery(report: dict) -> None:
    import logging

    logger = logging.getLogger("alerts-mcp")
    if report.get("unreachable"):
        logger.error(
            "cluster %r: UNREACHABLE — %s. Its brands are unknown, not empty.",
            settings.CLUSTER_NAME,
            report["unreachable"],
        )
    else:
        brands = report.get("discovered") or []
        logger.info(
            "cluster %r: discovered %d brand(s): %s", settings.CLUSTER_NAME, len(brands), ", ".join(brands) or "—"
        )


_auth = auth_settings()


def transport_security() -> TransportSecuritySettings:
    """Loopback plus the public host this server is reached through, with DNS-rebinding protection kept on."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    public = urlparse(settings.public_url())
    if public.netloc:
        hosts.append(public.netloc)
        origins.append(f"{public.scheme}://{public.netloc}")
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


mcp = FastMCP(
    "alert-bot-demo",
    instructions=INSTRUCTIONS,
    lifespan=lifespan,
    auth=_auth,
    token_verifier=CadminTokenVerifier() if _auth else None,
    stateless_http=True,
    json_response=True,
    streamable_http_path=settings.mcp_path(),
    transport_security=transport_security(),
)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_request: Request) -> JSONResponse:
    """Liveness, unauthenticated. Reports the brands startup found."""
    from mcp_server.storage import known_brands

    return JSONResponse(
        {
            "status": "ok",
            "clusters": {settings.CLUSTER_NAME: list(known_brands())},
            "brands": list(known_brands()),
        }
    )
