"""What the bot can alert on at all, and what each alert type does — read from the OpenSpec specifications."""

from typing import Any

from constants import CheckerCodes  # type: ignore[import-not-found]
from mcp_server import REPO_ROOT
from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.content.specs import (
    CONTRACT_SPEC,
    checker_spec_path,
    read_markdown,
    spec_outline,
    spec_purpose,
    spec_requirement,
)
from mcp_server.storage import validate_checker_code


@mcp.tool(title="List alert types", annotations=READ_ONLY_TOOL)
async def list_checker_types() -> list[dict[str, Any]]:
    """Every alert type this bot supports, with a one-line purpose read from its specification.

    The catalogue of what CAN be configured, independent of any brand. For what a brand actually
    has, use `list_alerts`; for the full documented behaviour of one type, `describe_checker_type`.
    """
    types: list[dict[str, Any]] = []
    for code in CheckerCodes:
        path = checker_spec_path(code.value)
        markdown = read_markdown(path)
        types.append(
            {
                "checker_code": code.value,
                "purpose": spec_purpose(markdown) if markdown else None,
                "specified": markdown is not None,
                "spec": str(path.relative_to(REPO_ROOT)) if markdown else None,
            }
        )
    return sorted(types, key=lambda item: item["checker_code"])


@mcp.tool(title="Describe an alert type", annotations=READ_ONLY_TOOL)
async def describe_checker_type(checker_code: str, requirement: str | None = None) -> dict[str, Any]:
    """The documented behaviour of one alert type: purpose, an outline of every requirement with its
    scenarios, and the full specification markdown. Pass `requirement` (full or partial title) for
    one requirement's text only. Every type also inherits `describe_alert_contract`."""
    code = validate_checker_code(checker_code)
    path = checker_spec_path(code)
    markdown = read_markdown(path)
    if markdown is None:
        return {
            "checker_code": code,
            "specified": False,
            "note": f"No specification exists for '{code}' yet; its behaviour is defined only by its implementation.",
        }
    result: dict[str, Any] = {
        "checker_code": code,
        "specified": True,
        "spec": str(path.relative_to(REPO_ROOT)),
        "purpose": spec_purpose(markdown),
        "outline": spec_outline(markdown),
        "inherits": "event-checking (see describe_alert_contract)",
    }
    if requirement:
        found = spec_requirement(markdown, requirement)
        if found is None:
            raise ValueError(
                f"No requirement matching '{requirement}' in the '{code}' specification. "
                f"Available: {[item['requirement'] for item in result['outline']]}"
            )
        result["requirement"] = {"name": found[0], "markdown": found[1]}
    else:
        result["markdown"] = markdown
    return result


@mcp.tool(title="The alert contract", annotations=READ_ONLY_TOOL)
async def describe_alert_contract(requirement: str | None = None) -> dict[str, Any]:
    """The contract EVERY alert type inherits, from the `event-checking` specification: per-brand
    configuration, validation hooks, brand isolation, the audience gates, deduplication, routing
    and journaling. Without arguments returns the outline only; pass `requirement` to read one."""
    markdown = read_markdown(CONTRACT_SPEC)
    if markdown is None:
        raise ValueError(f"The shared contract specification is missing at {CONTRACT_SPEC}")
    outline = spec_outline(markdown)
    result: dict[str, Any] = {
        "spec": str(CONTRACT_SPEC.relative_to(REPO_ROOT)),
        "purpose": spec_purpose(markdown),
        "outline": outline,
    }
    if requirement:
        found = spec_requirement(markdown, requirement)
        if found is None:
            raise ValueError(
                f"No requirement matching '{requirement}'. Available: {[i['requirement'] for i in outline]}"
            )
        result["requirement"] = {"name": found[0], "markdown": found[1]}
    return result
