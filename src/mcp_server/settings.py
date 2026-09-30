"""Every environment variable the MCP server reads, in one place. Values are read on access."""

import os

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8811
DEFAULT_MCP_PATH = "/mcp"
DEFAULT_PRINCIPAL_TTL_SECONDS = 60
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 5.0
SCOPE_READ = "alert-bot:read"
CLUSTER_NAME = "demo"


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mongo_uri() -> str:
    return _get("MONGO_URI", "mongodb://localhost:27017")


def transport() -> str:
    return _get("ALERTS_MCP_TRANSPORT", "stdio").lower() or "stdio"


def host() -> str:
    return _get("ALERTS_MCP_HOST", DEFAULT_HOST)


def port() -> int:
    try:
        return int(_get("ALERTS_MCP_PORT", str(DEFAULT_PORT)))
    except ValueError:
        return DEFAULT_PORT


def mcp_path() -> str:
    path = _get("ALERTS_MCP_PATH", DEFAULT_MCP_PATH) or DEFAULT_MCP_PATH
    return "/" + path.strip("/")


def public_url() -> str:
    """This server's externally reachable URL — the OAuth `resource` a token is bound to."""
    return _get("ALERTS_MCP_PUBLIC_URL").rstrip("/")


def cadmin_base_url() -> str:
    """The cadmin API root (with `/api/v1`). Required: without it nobody's permissions can be resolved."""
    return _get("ALERTS_MCP_CADMIN_BASE_URL").rstrip("/")


def cadmin_issuer() -> str:
    return _get("ALERTS_MCP_CADMIN_ISSUER").rstrip("/") or cadmin_base_url()


def cadmin_token() -> str:
    return _get("ALERTS_MCP_CADMIN_TOKEN")


def principal_ttl_seconds() -> int:
    try:
        return max(0, int(_get("ALERTS_MCP_PRINCIPAL_TTL_SECONDS", str(DEFAULT_PRINCIPAL_TTL_SECONDS))))
    except ValueError:
        return DEFAULT_PRINCIPAL_TTL_SECONDS


def discovery_timeout_seconds() -> float:
    try:
        return max(0.1, float(_get("ALERTS_MCP_DISCOVERY_TIMEOUT_SECONDS", str(DEFAULT_DISCOVERY_TIMEOUT_SECONDS))))
    except ValueError:
        return DEFAULT_DISCOVERY_TIMEOUT_SECONDS


def cadmin_review_base() -> str:
    """Where cadmin's review screen lives (the cadmin web host). A local cadmin by default."""
    return _get("ALERTS_MCP_CADMIN_REVIEW_BASE", "https://cadmin.test").rstrip("/")
