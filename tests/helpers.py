"""Test helpers that mirror what cadmin's Alert Bot proxy sends."""

import base64
import json
from typing import Any


def encode_filter(filter_dict: dict[str, Any]) -> str:
    """Byte-identical to cadmin's filter encoder: compact JSON, base64url, no padding."""
    raw = json.dumps(filter_dict, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
