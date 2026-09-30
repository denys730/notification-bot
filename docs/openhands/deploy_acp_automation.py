#!/usr/bin/env python3
"""Point the imported automation at the ACP runner.

Builds the tarball (`acp/main.py`, `acp/setup.sh`, the prompt as `prompt.txt`), uploads it to the
automation service and updates the automation in place: tarball, setup script, entrypoint and the
ACP agent profile it runs with. The trigger, name and enabled state are left alone.

    export OPENHANDS_AUTOMATION_API_KEY="..."
    python3 docs/openhands/deploy_acp_automation.py \
        --base https://<openhands-host> \
        --automation-id <automation-id> \
        --agent-profile-id <agent-profile-id>

Without --agent-profile-id the agent server's active agent profile is used. Re-run after every
edit of `acp/main.py` or the prompt: the prompt travels inside the bundle as `prompt.txt`, and the
automation's own `prompt` field stays empty so Agent Canvas lists the bundle's files.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "acp" / "main.py"
SETUP = HERE / "acp" / "setup.sh"
PROMPT = HERE / "alert-config-requested-prompt.md"
ENTRYPOINT = ".venv/bin/python main.py"


def build_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, path, mode in (("main.py", RUNNER, 0o644), ("setup.sh", SETUP, 0o755), ("prompt.txt", PROMPT, 0o644)):
            data = path.read_bytes()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def request(
    base: str, key: str, method: str, path: str, body: bytes | None = None, content_type: str = "application/json"
):
    http_request = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        method=method,
        headers={"X-Session-API-Key": key, **({"Content-Type": content_type} if body is not None else {})},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path} -> {error.code}: {error.read().decode('utf-8', 'replace')}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="OpenHands base URL, e.g. https://<openhands-host>")
    parser.add_argument("--automation-id", required=True)
    parser.add_argument("--agent-profile-id", default=None, help="ACP agent profile uuid (default: the active one)")
    args = parser.parse_args()
    key = os.environ.get("OPENHANDS_AUTOMATION_API_KEY", "").strip()
    if not key:
        print("set OPENHANDS_AUTOMATION_API_KEY", file=sys.stderr)
        return 2

    profile_id = args.agent_profile_id
    profiles = request(args.base, key, "GET", "/api/agent-profiles") or {}
    if profile_id is None:
        profile_id = profiles.get("active_agent_profile_id")
    profile = next((p for p in profiles.get("profiles", []) if p.get("id") == profile_id), None)
    if profile is None or profile.get("agent_kind") != "acp":
        print(f"agent profile {profile_id} is not an ACP profile on {args.base}: {profiles}", file=sys.stderr)
        return 1

    tarball = build_tarball()
    query = urllib.parse.urlencode(
        {
            "name": "alert-bot-demo-acp-runner",
            "description": "ACP runner + prompt for the alert_config.requested automation",
        }
    )
    upload = request(args.base, key, "POST", f"/api/automation/v1/uploads?{query}", tarball, "application/gzip") or {}
    tarball_path = upload.get("tarball_path")
    if not tarball_path:
        print(f"upload did not complete: {upload}", file=sys.stderr)
        return 1
    print(f"uploaded {len(tarball)} bytes -> {tarball_path}")

    # `prompt` is cleared on purpose: the runner reads `prompt.txt` from the bundle, and Agent Canvas
    # shows the bundle's files (the Script section) only for an automation without a prompt.
    patch = {
        "tarball_path": tarball_path,
        "setup_script_path": "setup.sh",
        "entrypoint": ENTRYPOINT,
        "agent_profile_id": profile_id,
        "prompt": None,
    }
    updated = (
        request(args.base, key, "PATCH", f"/api/automation/v1/{args.automation_id}", json.dumps(patch).encode()) or {}
    )

    summary = {
        k: updated.get(k)
        for k in (
            "id",
            "name",
            "enabled",
            "state",
            "agent_profile_id",
            "entrypoint",
            "setup_script_path",
            "tarball_path",
            "timeout",
        )
    }
    print(json.dumps(summary, indent=2))
    print(f"runs with ACP profile {profile.get('name')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
