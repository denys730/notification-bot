"""The guidance this server carries, and the brief every client receives at initialize.

Each guide is one Markdown file under `guides/` with a small front matter block; adding a guide is
adding a file. Nothing enumerates them by hand.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GUIDES_DIR = Path(__file__).resolve().parent / "guides"
GUIDE_URI_PREFIX = "alert-bot://guide/"
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)

PRIMARY_GUIDE = "operating-rules"


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    description: str
    body: str

    @property
    def uri(self) -> str:
        return f"{GUIDE_URI_PREFIX}{self.slug}"


def _parse(path: Path) -> Guide:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    meta, body = (match.group(1), text[match.end() :]) if match else ("", text)
    title = re.search(r"^title:\s*(.+)$", meta, re.M)
    description = re.search(r"^description:\s*(.+)$", meta, re.M)
    return Guide(
        slug=path.stem,
        title=title.group(1).strip() if title else path.stem,
        description=description.group(1).strip() if description else "",
        body=body.lstrip("\n"),
    )


@lru_cache(maxsize=1)
def load_guides() -> dict[str, Guide]:
    guides = {path.stem: _parse(path) for path in sorted(GUIDES_DIR.glob("*.md"))}
    if PRIMARY_GUIDE in guides:
        guides = {PRIMARY_GUIDE: guides[PRIMARY_GUIDE], **guides}
    return guides


def read_guide(slug: str) -> str:
    guides = load_guides()
    guide = guides.get(slug.strip().lower())
    if guide is None:
        raise ValueError(f"Unknown guide '{slug}'. Available: {', '.join(guides)}")
    return guide.body


def guide_catalogue() -> list[dict[str, str]]:
    return [
        {"name": g.slug, "title": g.title, "uri": g.uri, "description": g.description} for g in load_guides().values()
    ]


INSTRUCTIONS = """\
Read-only access to alert-bot-demo: alert configurations, the segmentation catalogue, player
segments, and the journal of alerts sent. Scoped to the brands cadmin grants you — `list_clusters`
shows which. This is a DEMO: the alert types are abstract, nothing runs on a schedule, and the
journal is seeded — the workflow is the one you would use in production.

Six rules that change what you do on the first call:

1. Report a segment by name AND value — `Business Premium (34)`. Every tool returns it ready in
   `label`; quote that, not the bare value.
2. Never loop `get_player_current_segments` over a list of players. Use
   `filter_players_by_segment` or `count_players_by_segment` — one aggregation instead of one
   round trip per player.
3. Nothing here writes an alert. To CHANGE one, call `propose_alert_changes`: it returns a cadmin
   review link where a human ticks what to apply. There is no `create_alert` / `update_alert` /
   `delete_alert`, and the absence is deliberate — do not go looking.
4. An alert's `segments` entries take the segment VALUE (`Business__34`), never the display name.
   Resolve with `list_segments` and validate with `validate_segments` — a value that does not
   exist narrows the audience to nobody, silently.
5. cadmin and the back office are reachable only through these tools. No direct HTTP, no database
   connection.
6. Before `propose_alert_changes`, compare the request with the live row (`get_alert`). Already
   configured that way = no link: answer that applying the change would change nothing.

`list_guides()` lists the guidance this server carries: the operating rules, administering alerts,
and how to write a change proposal. Read `operating-rules` first.\
"""
