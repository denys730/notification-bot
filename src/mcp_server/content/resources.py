"""The guides as MCP resources, prompts and tools — three surfaces over the same files, because clients differ."""

from mcp_server.app import READ_ONLY_TOOL, mcp
from mcp_server.content.catalogue import PRIMARY_GUIDE, guide_catalogue, load_guides, read_guide


def _register_guide_resources() -> None:
    for guide in load_guides().values():

        def _make_reader(slug: str):
            def _reader() -> str:
                return read_guide(slug)

            return _reader

        mcp.resource(guide.uri, name=guide.title, description=guide.description, mime_type="text/markdown")(
            _make_reader(guide.slug)
        )


_register_guide_resources()


@mcp.prompt(
    name="alert_bot_operating_rules",
    title="alert-bot-demo: operating rules",
    description="Load the working rules before answering a question about alerts, segments or alert history.",
)
def operating_rules_prompt() -> str:
    return read_guide(PRIMARY_GUIDE)


@mcp.prompt(
    name="alert_bot_propose_changes",
    title="alert-bot-demo: propose alert changes",
    description="Load the rules for writing an alert-change proposal before building one.",
)
def propose_changes_prompt() -> str:
    return read_guide("proposing-changes")


@mcp.tool(title="List guides", annotations=READ_ONLY_TOOL)
async def list_guides() -> list[dict[str, str]]:
    """The guidance this server carries — read one with `read_guide(name)`. Read `operating-rules` first."""
    return guide_catalogue()


@mcp.tool(name="read_guide", title="Read a guide", annotations=READ_ONLY_TOOL)
async def read_guide_tool(name: str) -> str:
    """Read one guide in full, by the `name` from `list_guides`."""
    return read_guide(name)


def guide_names() -> list[str]:
    return list(load_guides())
