"""Read-only MCP server over the demo's data and its own documentation.

It lives under `src/` with the API it reads and shares its code: the Mongo layout in
`storage.mongo`, the `CheckerCodes` enum, the checker specifications under `openspec/specs/`.
What it does NOT share is `settings.BRANDS`: brands are discovered from the database, so the two
processes cannot disagree about what exists.
"""

from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
# The repository: the checker specifications live in `openspec/specs/`, outside `src/`.
REPO_ROOT = PACKAGE_ROOT.parent.parent

load_dotenv(REPO_ROOT / ".env")
