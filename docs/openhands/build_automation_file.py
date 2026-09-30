#!/usr/bin/env python3
"""Build the OpenHands automation import file from the prompt next to it.

The prompt lives in `alert-config-requested-prompt.md` so it can be reviewed and diffed as text;
Agent Canvas imports a versioned JSON document, so this script wraps the prompt in that envelope.
Re-run it after every edit of the prompt:

    python3 docs/openhands/build_automation_file.py          # writes the .automation.json
    python3 docs/openhands/build_automation_file.py --check  # validates an existing file only

The checks mirror what Agent Canvas's importer (`parseAutomationFile`) rejects, so a file that
passes here passes the import dialog. Imported automations are always created disabled.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT_FILE = HERE / "alert-config-requested-prompt.md"
OUTPUT_FILE = HERE / "alert-bot-demo-alert-config-requested.automation.json"

# Agent Canvas envelope (extensions catalogue `automations/interface.json` -> importExport).
FILE_VERSION = 1
FILE_KIND = "automation"

SPEC_WITHOUT_PROMPT = {
    "name": "Alert Bot Demo: alert_config.requested",
    "trigger": {
        # A custom webhook source registered in OpenHands under this name; the sender posts the
        # request object, OpenHands reads the event key from its `type` (default event_key_expr).
        "type": "event",
        "source": "ops-service",
        "on": "alert_config.requested",
        # JMESPath over the raw webhook body: only Alert Bot requests start this automation.
        "filter": "application == 'Alert Bot Demo'",
    },
    "enabled": False,
    # Seconds. The code path (spec, checker, tests, MR) needs the longest run the deployment
    # allows; OpenHands Cloud caps a run at 1800.
    "timeout": 1800,
}


def build() -> dict:
    prompt = PROMPT_FILE.read_text(encoding="utf-8").strip() + "\n"
    spec = dict(SPEC_WITHOUT_PROMPT)
    spec["prompt"] = prompt
    return {"version": FILE_VERSION, "kind": FILE_KIND, "spec": spec}


def problems(document: object) -> list[str]:
    """Every reason Agent Canvas's importer would refuse this file."""
    issues: list[str] = []
    if not isinstance(document, dict):
        return ["file: expected a JSON object"]
    if document.get("version") != FILE_VERSION:
        issues.append(f"version: expected {FILE_VERSION}")
    if document.get("kind") != FILE_KIND:
        issues.append(f'kind: expected "{FILE_KIND}"')
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return issues + ["spec: expected an object"]
    for field in ("name", "prompt"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            issues.append(f"spec.{field}: expected a non-empty string")
    trigger = spec.get("trigger")
    if not isinstance(trigger, dict):
        issues.append("spec.trigger: expected an object")
    else:
        kind = trigger.get("type")
        if kind not in ("cron", "schedule", "event"):
            issues.append('spec.trigger.type: expected one of "cron", "schedule", or "event"')
        if kind in ("cron", "schedule") and not str(trigger.get("schedule") or "").strip():
            issues.append("spec.trigger.schedule: required for a scheduled trigger")
        if kind == "event":
            if not str(trigger.get("source") or "").strip():
                issues.append("spec.trigger.source: required for an event trigger")
            on = trigger.get("on")
            ok = (isinstance(on, str) and on.strip()) or (
                isinstance(on, list) and on and all(isinstance(e, str) and e.strip() for e in on)
            )
            if not ok:
                issues.append("spec.trigger.on: required for an event trigger")
        for key in ("schedule", "schedule_human", "timezone", "source", "filter"):
            if key in trigger and not isinstance(trigger[key], str):
                issues.append(f"spec.trigger.{key}: expected a string")
    if not isinstance(spec.get("enabled"), bool):
        issues.append("spec.enabled: expected a boolean")
    for key in ("repository", "branch", "notification", "timezone"):
        if key in spec and not isinstance(spec[key], str):
            issues.append(f"spec.{key}: expected a string")
    if "model" in spec and spec["model"] is not None:
        if not isinstance(spec["model"], str) or not spec["model"].strip():
            issues.append("spec.model: expected a non-empty string or null")
    if "timeout" in spec and spec["timeout"] is not None:
        if isinstance(spec["timeout"], bool) or not isinstance(spec["timeout"], int) or spec["timeout"] <= 0:
            issues.append("spec.timeout: expected a positive integer")
    if "plugins" in spec:
        plugins = spec["plugins"]
        if not isinstance(plugins, list) or not all(isinstance(x, str) and x.strip() for x in plugins):
            issues.append("spec.plugins: expected an array of non-empty strings")
    return issues


def main() -> int:
    if "--check" in sys.argv[1:]:
        document = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    else:
        document = build()
        OUTPUT_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {OUTPUT_FILE.relative_to(HERE.parent.parent)}")
    found = problems(document)
    for issue in found:
        print(f"  - {issue}", file=sys.stderr)
    print("ok: importable" if not found else "refused by the importer", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
