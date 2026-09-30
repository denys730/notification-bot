---
title: Administering alerts
description: Use when managing alert configurations through this server — a request asks to add, change, enable/disable or remove alerts for a brand; or someone asks which alerts exist, what can be configured, what an alert does, or why an alert fired. Carries the catalogue of the four demo alert types with their knobs and example configs.
---

# alert-bot-demo alerts administration

Alerts are rows of `checkers_configs`; the MCP routes every call by `brand`. If the MCP is not
connected: `claude mcp add --transport http alert-bot-demo http://<host>:8811/mcp`, then sign in
through cadmin. A client that cannot open a browser (OpenHands, CI) sends `Authorization: Bearer
<token>` with a personal API token created in cadmin under Account settings → API tokens.

Checker codes are lowercase snake_case (`threshold_breach`, NOT `THRESHOLD_BREACH`). Config keys
and example values come from the catalogue below and from `describe_checker_type`, never from
memory.

## Data model facts that change decisions

- Uniqueness is `(brand, checker_name)` — a brand can have **several** alerts with the same
  `checker_code`. "Add an alert" is usually a genuine create with a descriptive `checker_name`
  (convention: `"<Checker> <threshold> <window> <audience>"`, e.g. `Threshold Breach 5000 24h`).
- Rows are seeded per brand, so **always** `list_alerts(brand=...)` before planning: the request
  may be an update or enable of an existing row instead of a create.
- Thresholds, windows, frequencies and TTLs are product decisions. Take values from the requester;
  never invent them. If the request is silent, propose the catalogue example marked as a question.

## Workflow for change requests

1. **Read the request.** Extract: brand(s), desired alerts, thresholds/windows, audience (VIP /
   non-VIP, segments, regions), destination channels, cadence.
2. **Inventory.** `list_alerts(brand=...)`, and `list_segments` if segments are involved.
3. **Compare.** For each item: already in force (equal values — nothing to propose), already exists
   (differs — an update, not a create), create, delete, questions.
4. **Propose.** `propose_alert_changes` once per brand that changes, per the `proposing-changes`
   guide. Hand over the link and say what the reviewer is approving.

## Segments rules

- The `segments` field takes `{segmentation_id}__{segment_value}` strings — the **value**, not the
  name. Resolve with `list_segments(brand=..., query=...)`, use `config_entry` verbatim, then
  `validate_segments`.
- Report a segment by name AND value: `Business Premium (34)`.
- Never resolve a group of players one at a time; see the operating rules.

## Q&A requests (no writes)

- "Which alerts does brand X have?" → `list_alerts(brand=...)`; summarise name, code, enabled,
  threshold/window, channels, segments, regions.
- "What can we set up?" → `list_checker_types()`, one line per type.
- "What does this alert do?" → `describe_checker_type(code)` plus the brand's actual row.
- "What fired last week?" → `list_alert_journal(brand, since=..., until=...)`.

---

# Reference: checkers

## Shared gates and knobs (from the base checker)

Every row carries `channels` (Slack channels; first is primary), `segments` (allow list of
`{segmentation_id}__{value}`), `regions` (allow list of registration regions, case-insensitive),
`frequency_minutes` or `cron`, `max_instances`, `enabled`. Inside `config`, player-targeted checkers
read `check_vip_users` / `check_non_vip_users` (both default true) and `mentions` (Slack user ids
to tag). Deduplication is per entity with a TTL each checker names below.

### heartbeat — service-level, monitoring channel

Probes the service's own dependencies in order and stops at the first failure. No audience gates,
no deduplication. `config` is empty.

```json
{"checker_code": "heartbeat", "checker_name": "Heartbeat", "frequency_minutes": 30, "config": {}}
```

### threshold_breach — per entity; VIP, segment and region gates

An entity's successful amounts, summed over a rolling `monitoring_window_hours`, reach `threshold`.
Suppression TTL = the window. Optional `event_kind` restricts the sum to one kind of event.

| Knob | Required | Bounds | Meaning |
| --- | --- | --- | --- |
| `monitoring_window_hours` | yes | 1–168 | rolling window and suppression TTL |
| `threshold` | yes | ≥ 0 | the sum that fires |
| `event_kind` | no | | only sum events of this kind |
| `check_vip_users`, `check_non_vip_users` | no | | audience flags |
| `mentions` | no | | Slack user ids to tag |

```json
{"checker_code": "threshold_breach", "checker_name": "Threshold Breach 5000 24h", "frequency_minutes": 15,
 "config": {"monitoring_window_hours": 24, "threshold": 5000, "event_kind": "inflow", "check_vip_users": true, "check_non_vip_users": true, "mentions": {}}}
```

### activity_drop — brand-level; the gates restrict the cohort

Event volume in the last `window_minutes` falls at least `drop_percent` below the average of the
same slot over the previous `baseline_days` days. Skipped while the baseline averages fewer than
`min_baseline_events`. One alert per brand per window.

| Knob | Required | Bounds |
| --- | --- | --- |
| `window_minutes` | yes | 5–1440 |
| `baseline_days` | yes | 1–7 |
| `drop_percent` | yes | 1–100 |
| `min_baseline_events` | no (default 20) | |

### status_stuck — per entity; VIP, segment and region gates

An entity's latest event has stayed in one of `pending_statuses` (default `["pending"]`) for more
than `pending_minutes`. Suppression TTL `cache_ttl_hours` (default 24).

| Knob | Required | Bounds |
| --- | --- | --- |
| `pending_minutes` | yes | 1–10080 |
| `pending_statuses` | no | |
| `cache_ttl_hours` | no (default 24) | |

### first_event_breach — per entity; VIP, segment and region gates

An entity's FIRST successful event of `event_kind` reaches `threshold` less than
`max_entity_age_hours` after the entity's registration event (the earliest event of
`registration_kind`). The age is measured at the event, not at the run. Suppression TTL
`cache_ttl_hours` (default 24).

| Knob | Required | Bounds | Meaning |
| --- | --- | --- | --- |
| `threshold` | yes | ≥ 0 | the amount the first event must reach |
| `max_entity_age_hours` | yes | 1–168 | the entity must be younger than this at that event |
| `event_kind` | yes | | the kind of event the rule watches |
| `registration_kind` | no (default `registration`) | | the kind of event that marks registration |
| `cache_ttl_hours` | no (default 24) | | suppression TTL |
| `check_vip_users`, `check_non_vip_users` | no | | audience flags |
| `mentions` | no | | Slack user ids to tag |

```json
{"checker_code": "first_event_breach", "checker_name": "First Event Breach 1000 24h", "frequency_minutes": 15,
 "config": {"threshold": 1000, "max_entity_age_hours": 24, "event_kind": "inflow", "registration_kind": "registration", "cache_ttl_hours": 24, "check_vip_users": true, "check_non_vip_users": true, "mentions": {}}}
```

## Checkers that honour the top-level `segments` gate

`threshold_breach`, `status_stuck`, `first_event_breach` (per entity); `activity_drop` (cohort).
Not `heartbeat`.
