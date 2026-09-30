"""The MCP server's entry point — `uv run python src/mcp_server/main.py`.

Importing `mcp_server.tools` is what registers the tools, resources and prompts; it must happen
before the app is served.
"""

if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))


import asyncio
import logging

from mcp_server import (
    settings,
    tools,  # noqa: F401 — import side effect: registers the MCP surface
)
from mcp_server.app import log_discovery, mcp
from mcp_server.auth.cadmin import resolve_principal
from mcp_server.auth.principal import set_principal

logger = logging.getLogger("alerts-mcp")


def _require(value: str, message: str) -> str:
    if not value:
        raise SystemExit(message)
    return value


def _run_stdio() -> None:
    token = _require(
        settings.cadmin_token(),
        "ALERTS_MCP_CADMIN_TOKEN must hold your cadmin access token to run over stdio. "
        "Use the HTTP transport to authorize through cadmin in a browser instead.",
    )
    set_principal(asyncio.run(resolve_principal(token)))
    mcp.run()


def _with_startup_discovery(app):
    """Discover brands once when the ASGI app starts, on the loop that will serve requests."""
    from contextlib import asynccontextmanager

    from mcp_server.storage import ensure_discovered

    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(scope_app):
        async with inner(scope_app):
            report = await ensure_discovered()
            if report is not None:
                log_discovery(report)
            yield

    app.router.lifespan_context = lifespan
    return app


def _run_http() -> None:
    _require(
        settings.public_url(),
        "ALERTS_MCP_PUBLIC_URL must be this server's externally reachable URL — the OAuth `resource` "
        "clients bind their token to.",
    )
    if mcp.settings.auth is None:  # pragma: no cover
        raise SystemExit("OAuth is not configured; set ALERTS_MCP_CADMIN_BASE_URL and ALERTS_MCP_PUBLIC_URL.")

    import uvicorn

    app = _with_startup_discovery(mcp.streamable_http_app())
    uvicorn.run(app, host=settings.host(), port=settings.port(), log_config=None)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    _require(
        settings.cadmin_base_url(),
        "ALERTS_MCP_CADMIN_BASE_URL is not set — the server cannot resolve anyone's permissions.",
    )
    transport = settings.transport()
    if transport == "stdio":
        _run_stdio()
    elif transport == "http":
        _run_http()
    else:
        raise SystemExit(f"Unknown ALERTS_MCP_TRANSPORT {transport!r}. Use 'stdio' or 'http'.")


if __name__ == "__main__":
    main()
