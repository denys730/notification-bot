"""Reading alert behaviour out of the OpenSpec specifications. Directory names are the checker code in kebab-case."""

import re
from pathlib import Path
from typing import Any

from mcp_server import REPO_ROOT

SPECS_DIR = REPO_ROOT / "openspec" / "specs"
CHECKER_SPECS_DIR = SPECS_DIR / "checkers"
CONTRACT_SPEC = SPECS_DIR / "event-checking" / "spec.md"


def checker_spec_path(checker_code: str) -> Path:
    return CHECKER_SPECS_DIR / checker_code.replace("_", "-") / "spec.md"


def read_markdown(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def spec_purpose(markdown: str) -> str:
    match = re.search(r"^## Purpose\s*\n(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    paragraph = match.group(1).strip().split("\n\n", 1)[0]
    return re.sub(r"\s+", " ", paragraph).strip()


def spec_outline(markdown: str) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for line in markdown.splitlines():
        requirement = re.match(r"^### Requirement:\s*(.+?)\s*$", line)
        if requirement:
            outline.append({"requirement": requirement.group(1), "scenarios": []})
            continue
        scenario = re.match(r"^#### Scenario:\s*(.+?)\s*$", line)
        if scenario and outline:
            outline[-1]["scenarios"].append(scenario.group(1))
    return outline


def spec_requirement(markdown: str, name: str) -> tuple[str, str] | None:
    blocks = re.findall(r"^### Requirement:\s*(.+?)\s*$\n(.*?)(?=^### |\Z)", markdown, re.MULTILINE | re.DOTALL)
    needle = name.strip().lower()
    for title, body in blocks:
        if needle == title.lower():
            return title, body.strip()
    for title, body in blocks:
        if needle in title.lower():
            return title, body.strip()
    return None
