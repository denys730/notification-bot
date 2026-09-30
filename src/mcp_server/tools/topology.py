"""Which brands exist on this server — as far as the caller may see."""

from typing import Any

from mcp_server import settings
from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.auth.principal import current_principal
from mcp_server.storage import discover_brands, known_brands, readable_brands, redact_uri


@mcp.tool(title="Brands and clusters", annotations=READ_ONLY_TOOL)
async def list_clusters(refresh: bool = False) -> dict[str, Any]:
    """The brands you can work with, and the (single, in this demo) Mongo cluster they live on.

    Scoped to YOUR grants: cadmin decides per (brand, service). `granted_services` names the exact
    Alert Bot service rows behind that list — the `slug` there is what `propose_alert_changes` needs.

    Brands are discovered from the database at startup (every `alert_bot_<brand>` database is one).
    Pass `refresh=True` to re-read them after a brand was seeded while this server was running.
    """
    report = await discover_brands() if refresh else None
    principal = current_principal()
    visible = readable_brands(principal)
    brands = list(known_brands()) if visible is None else sorted(visible)
    result: dict[str, Any] = {
        "clusters": [{"cluster": settings.CLUSTER_NAME, "uri": redact_uri(settings.mongo_uri()), "brands": brands}]
    }
    if principal is not None:
        result = {
            "identity": principal.email,
            "is_superuser": principal.is_superuser,
            "brands": sorted(principal.brands),
            "granted_services": [{"slug": s.slug, "name": s.name, "brand": s.brand} for s in principal.services],
            **result,
        }
    if report is not None:
        result["discovery"] = {"unreachable": report["unreachable"]} if report.get("unreachable") else {"status": "ok"}
    return result
