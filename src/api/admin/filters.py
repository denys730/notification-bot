"""The list-filter language of the admin API: `?filter=<base64url JSON>`.

cadmin packs every list filter this way (`checker_name.icontains`, `id.in`, `regions.isnull`, grouped
under `$and` / `$or` / `$not`), so the language is the contract and must not change. A key is
`<field path>.<lookup>`; the trailing segment counts as a lookup only when it is one of
`SUPPORTED_LOOKUPS`, which is what lets `context.provider` be a nested field rather than an error.
"""

import base64
import json
import re
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status

SUPPORTED_LOOKUPS = frozenset(
    {
        "exact",
        "iexact",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "in",
        "gt",
        "gte",
        "lt",
        "lte",
        "range",
        "isnull",
        "regex",
        "iregex",
    }
)


def decode_filter(filter_str: str) -> dict[str, Any]:
    try:
        padding = len(filter_str) % 4
        if padding:
            filter_str += "=" * (4 - padding)
        return json.loads(base64.urlsafe_b64decode(filter_str).decode("utf-8"))
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid filter format: {error}")


def parse_field_lookup(key: str) -> tuple[str, str | None]:
    field_path, _, tail = key.rpartition(".")
    if field_path and tail in SUPPORTED_LOOKUPS:
        return field_path, tail
    return (f"{field_path}.{tail}" if field_path else tail), None


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _object_id(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return ObjectId(value)
    except Exception:
        raise _bad(f"Invalid ObjectId format: {value}")


def build_mongo_query(filter_dict: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(filter_dict, dict):
        raise _bad("Filter must be a JSON object")

    for group in ("$and", "$or"):
        if group in filter_dict:
            conditions = filter_dict[group]
            if not isinstance(conditions, list) or not all(isinstance(item, dict) for item in conditions):
                raise _bad(f"{group} conditions must be objects")
            built = [build_mongo_query(item) for item in conditions]
            return {group: built} if built else {}
    if "$not" in filter_dict:
        if not isinstance(filter_dict["$not"], dict):
            raise _bad("$not condition must be an object")
        return {"$not": build_mongo_query(filter_dict["$not"])}

    query: dict[str, Any] = {}
    for key, value in filter_dict.items():
        if key.startswith("$"):
            continue
        field_name, lookup = parse_field_lookup(key)
        mongo_field = "_id" if field_name == "id" else field_name
        if field_name == "id":
            value = [_object_id(item) for item in value] if lookup == "in" and isinstance(value, list) else value
            value = _object_id(value) if lookup in (None, "exact") else value

        if lookup is None or lookup == "exact":
            query[mongo_field] = value
        elif lookup == "iexact":
            query[mongo_field] = {"$regex": f"^{re.escape(str(value))}$", "$options": "i"}
        elif lookup == "contains":
            query[mongo_field] = {"$regex": re.escape(str(value))}
        elif lookup == "icontains":
            query[mongo_field] = {"$regex": re.escape(str(value)), "$options": "i"}
        elif lookup == "startswith":
            query[mongo_field] = {"$regex": f"^{re.escape(str(value))}"}
        elif lookup == "istartswith":
            query[mongo_field] = {"$regex": f"^{re.escape(str(value))}", "$options": "i"}
        elif lookup == "endswith":
            query[mongo_field] = {"$regex": f"{re.escape(str(value))}$"}
        elif lookup == "iendswith":
            query[mongo_field] = {"$regex": f"{re.escape(str(value))}$", "$options": "i"}
        elif lookup == "in":
            if not isinstance(value, list):
                raise _bad("'in' lookup requires a list value")
            query[mongo_field] = {"$in": value}
        elif lookup in ("gt", "gte", "lt", "lte"):
            query[mongo_field] = {f"${lookup}": value}
        elif lookup == "range":
            if not isinstance(value, list) or len(value) != 2:
                raise _bad("'range' lookup requires a list with exactly 2 elements")
            query[mongo_field] = {"$gte": value[0], "$lte": value[1]}
        elif lookup == "isnull":
            query[mongo_field] = None if value else {"$ne": None}
        elif lookup == "regex":
            query[mongo_field] = {"$regex": str(value)}
        elif lookup == "iregex":
            query[mongo_field] = {"$regex": str(value), "$options": "i"}
        else:  # pragma: no cover — SUPPORTED_LOOKUPS gates this
            raise _bad(f"Unsupported lookup type: {lookup}")
    return query


def build_sort(sort_fields: list[str]) -> list[tuple[str, int]]:
    """`-field` sorts descending; `id` means `_id`."""
    out: list[tuple[str, int]] = []
    for item in sort_fields:
        direction = -1 if item.startswith("-") else 1
        name = item.lstrip("-")
        out.append(("_id" if name == "id" else name, direction))
    return out


def parse_boolean(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")
