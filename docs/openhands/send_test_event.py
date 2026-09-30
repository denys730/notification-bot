#!/usr/bin/env python3
"""Send one signed `alert_config.requested` event to the OpenHands webhook, by hand.

The URL and the signing secret come from registering the `ops-service` webhook source in
OpenHands (`POST /api/automation/v1/webhooks`); the automation subscribes to that source.

    export OPENHANDS_WEBHOOK_URL="https://<host>/api/automation/v1/events/<org_id>/ops-service"
    export OPENHANDS_WEBHOOK_SECRET="whsec_..."
    python3 docs/openhands/send_test_event.py [request.json]

Without a file it sends the sample request below. The body is signed exactly as sent: the header
`X-Signature-256` carries `sha256=<hex HMAC-SHA256 of the raw bytes>`, which is what the default
`hmac_sha256_hex` scheme of a custom webhook verifies. The response says whether the automation
matched (`matched`) and which run it started (`runs_created`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

SAMPLE_REQUEST = {
    # OpenHands reads the event key from `type` (the webhook's default `event_key_expr`).
    "type": "alert_config.requested",
    "id": "REQ-TEST0001",
    "request_id": "REQ-TEST0001",
    "brands": ["DEMO"],
    "title": "Alert when a Premium entity reaches 2,000 within one hour",
    "description": "Test request: replace with a real one before enabling the automation.",
    "requested_by": "swat-team",
    "callback_url": "http://localhost:8070/api/openhands/callback/REQ-TEST0001?token=test",
    "sent_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "source": "capybara",
    "application": "Alert Bot Demo",
    "capybara_task_id": 0,
}


def main() -> int:
    url = os.environ.get("OPENHANDS_WEBHOOK_URL", "").strip()
    secret = os.environ.get("OPENHANDS_WEBHOOK_SECRET", "").strip()
    if not url or not secret:
        print("set OPENHANDS_WEBHOOK_URL and OPENHANDS_WEBHOOK_SECRET first", file=sys.stderr)
        return 2
    request = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else SAMPLE_REQUEST
    body = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    http_request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Signature-256": f"sha256={digest}"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            print(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        print(error.code, error.read().decode("utf-8"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
