"""Turning a set of proposed alert changes into a cadmin review link — the only way alerts get edited here.

The payload rides in the URL fragment, which never leaves the browser. The wire format is cadmin's
contract (its `alert-proposal-link-format` document):

    JSON (UTF-8, compact) -> raw DEFLATE -> [codec byte] + body -> base64url, unpadded
"""

import base64
import json
import zlib
from datetime import UTC, datetime
from typing import Any

from mcp_server import settings
from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.auth.principal import current_principal
from mcp_server.storage import validate_checker_code

CODEC_RAW_DEFLATE = 0x01
SCHEMA_VERSION = 1

# The ten keys cadmin knows how to apply. Anything else reaches the reviewer as "will NOT be applied".
SET_KEYS = {
    "checker_name",
    "description",
    "cron",
    "enabled",
    "frequency_minutes",
    "max_instances",
    "channels",
    "segments",
    "regions",
    "config",
}
LIST_KEYS = {"channels", "segments", "regions"}
CONFIG_ONLY_HINTS = {"threshold", "monitoring_window_hours", "window_minutes", "pending_minutes", "mentions"}


def encode_proposal(proposal: dict[str, Any]) -> str:
    raw = json.dumps(proposal, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = compressor.compress(raw) + compressor.flush()
    return base64.urlsafe_b64encode(bytes([CODEC_RAW_DEFLATE]) + body).decode("ascii").rstrip("=")


def decode_proposal(token: str) -> dict[str, Any]:
    padded = token + "=" * (-len(token) % 4)
    data = base64.urlsafe_b64decode(padded)
    if not data:
        raise ValueError("Empty proposal token")
    codec, body = data[0], data[1:]
    if codec == CODEC_RAW_DEFLATE:
        body = zlib.decompress(body, -15)
    elif codec != 0x00:
        raise ValueError(f"Unknown codec byte 0x{codec:02x}")
    return json.loads(body)


def _is_object_id(value: Any) -> bool:
    text = str(value)
    return len(text) == 24 and text.strip("0123456789abcdefABCDEF") == ""


def validate_change(index: int, change: dict[str, Any], errors: list[str]) -> None:
    where = f"changes[{index}]"
    op = change.get("op", "upsert")
    if op not in ("upsert", "delete"):
        errors.append(f"{where}: op must be 'upsert' or 'delete', got {op!r}")
    alert_id = change.get("id")
    if alert_id is not None and not _is_object_id(alert_id):
        errors.append(f"{where}: id must be a 24-character hex ObjectId, got {alert_id!r}")
    if op == "delete":
        if not alert_id:
            errors.append(f"{where}: a delete needs the alert's id")
        return
    changes = change.get("set")
    if not isinstance(changes, dict) or not changes:
        errors.append(f"{where}: an upsert needs a non-empty 'set'")
        return
    for key in sorted(set(changes) - SET_KEYS):
        hint = " — alert knobs belong inside set.config" if key in CONFIG_ONLY_HINTS else ""
        errors.append(f"{where}: '{key}' is not a key cadmin applies{hint}")
    if not alert_id:
        if not change.get("code"):
            errors.append(f"{where}: a create needs 'code' (the checker_code)")
        if not changes.get("checker_name"):
            errors.append(f"{where}: a create needs set.checker_name")
    if change.get("code"):
        try:
            validate_checker_code(str(change["code"]))
        except ValueError as error:
            errors.append(f"{where}: {error}")
    if not str(change.get("reason") or "").strip():
        errors.append(
            f"{where}: 'reason' is missing. The reviewer is judging whether to trust a machine, and the "
            f"reason is what they judge — cite evidence, not intent."
        )


@mcp.tool(title="Propose alert changes", annotations=READ_ONLY_TOOL)
async def propose_alert_changes(
    brand: str,
    service_slug: str,
    changes: list[dict[str, Any]],
    title: str | None = None,
    note: str | None = None,
    cadmin_base: str | None = None,
) -> dict[str, Any]:
    """Build a cadmin review link for a set of proposed alert changes — the way alerts get edited.

    There is no `create_alert` / `update_alert` / `delete_alert` here, deliberately: you propose, a
    human reviews field by field in cadmin, and only the rows they tick are applied.

    Each entry of `changes` is:

        {"id": "<24-hex>",              # present = update, absent = create
         "op": "upsert" | "delete",     # default upsert
         "code": "threshold_breach",    # required on create; a guard on update
         "name": "Threshold Breach 5000 24h",   # the name as you saw it — a guard, never identity
         "reason": "Fired 6x in 5 days for 3 entities; every one was a Premium entity above 5,000",
         "set": {"config": {"threshold": 4000}}}

    `set` is partial. `config` MERGES per key (a key set to null is removed); `channels`, `segments`
    and `regions` REPLACE the whole list, so `[]` clears them. A threshold goes inside `config`.

    `service_slug` is the `slug` of that brand's entry in `list_clusters().granted_services` — read
    it, never derive it from the brand code. `cadmin_base` defaults to the configured cadmin host.

    Returns the link plus a per-row summary. Print the link whole, on its own line: the payload is a
    URL fragment, and a wrapped or truncated link opens an empty review screen.
    """
    brand = brand.strip().upper()
    principal = current_principal()
    if principal is not None:
        principal.require(brand)

    slug = service_slug.strip()
    errors: list[str] = []
    if not slug:
        errors.append("service_slug is required — cadmin addresses everything by slug, never by brand code")
    if not changes:
        errors.append("changes must hold at least one entry")
    for index, change in enumerate(changes):
        validate_change(index, change, errors)
    if errors:
        raise ValueError("The proposal was not encoded:\n  - " + "\n  - ".join(errors))

    proposal: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "service": slug,
        "brand": brand,
        "author": "alert-bot-demo-mcp",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "changes": changes,
    }
    if title:
        proposal["title"] = title
    if note:
        proposal["note"] = note

    token = encode_proposal(proposal)
    if decode_proposal(token) != proposal:
        raise ValueError("Encoded proposal did not survive a round trip — refusing to hand over the link")

    def _kind(change: dict[str, Any]) -> str:
        if change.get("op") == "delete":
            return "delete"
        return "update" if change.get("id") else "create"

    base = (cadmin_base or settings.cadmin_review_base()).rstrip("/")
    return {
        "link": f"{base}/s/{slug}/checkers/review#{token}",
        "brand": brand,
        "service_slug": slug,
        "summary": [
            {
                "kind": _kind(change),
                "alert": change.get("name") or change.get("set", {}).get("checker_name") or change.get("id"),
                "reason": change.get("reason"),
            }
            for change in changes
        ],
        "next_step": (
            "Print this link whole and, when a browser exists, open it. The proposal lives after the '#'. "
            "Say what the reviewer is approving rather than only handing over a URL. Applying is not "
            "transactional: rows go one at a time."
        ),
    }
