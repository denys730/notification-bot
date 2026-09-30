"""Importing this package registers the whole MCP surface against the shared app."""

from mcp_server.content import resources  # noqa: F401 — registers the guides as resources/prompts
from mcp_server.tools import (  # noqa: F401
    alerts,
    checker_types,
    journal,
    proposals,
    segments,
    topology,
)

__all__ = ["alerts", "checker_types", "journal", "proposals", "resources", "segments", "topology"]
