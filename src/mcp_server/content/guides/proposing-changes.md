---
title: Proposing alert changes
description: Use for EVERY request to add, create, change, retune, enable, disable, rename or delete an alert for a brand — there is no MCP tool that applies such a change and its absence is deliberate. Packs the change set into a cadmin review link that renders like a merge request, current value against proposed value with your reasoning per alert, so a human ticks what to apply. Covers the envelope, the `set` merge-versus-replace semantics, the service/brand guards, and the encoder.
---

# cadmin alert-proposal review links

## 1. When to apply

**Every** request to add, change, enable, disable, rename or delete an alert goes through this.
Do not go looking for an MCP tool that applies the change — there isn't one, and its absence is
deliberate. You propose, a human reviews field by field, and cadmin applies only the rows they tick.

**Check before you propose.** Read the live row(s) with `get_alert` / `list_alerts` and compare
with the request. A request the brand already satisfies is answered with "already configured this
way; applying it would change nothing", and NO link is built. A matching row that is disabled is a
real change: propose `enabled: true`.

## 2. The link

```
{cadmin_BASE}/s/{service_slug}/checkers/review#{token}
```

The payload lives in the URL **fragment**, which never leaves the browser. `propose_alert_changes`
builds it; the wire format is cadmin's contract (its `alert-proposal-link-format` document):

```
JSON (UTF-8, compact)  ->  deflate-raw  ->  [codec byte 0x01] + body  ->  base64url, no padding
```

Reference encoder, stdlib only — for the case where the deployed server refuses a checker code it
does not know yet (a brand-new type on an unmerged branch):

```python
import base64, json, zlib


def proposal_link(proposal: dict, cadmin_base: str) -> str:
    raw = json.dumps(proposal, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)  # -15 = raw DEFLATE, no zlib header
    body = compressor.compress(raw) + compressor.flush()
    token = base64.urlsafe_b64encode(bytes([0x01]) + body).decode("ascii").rstrip("=")
    return f"{cadmin_base.rstrip('/')}/s/{proposal['service']}/checkers/review#{token}"
```

**Print the link whole, on its own line, and open it when a browser exists.** A terminal wraps a
long fragment and a click takes only the first line; everything after `#` is the proposal.

## 3. The one thing to look up, never guess

**The service slug.** cadmin addresses everything by service slug, never by brand code. Read it from
`list_clusters().granted_services` — the `slug` of the entry whose `brand` is the one you propose
for. A wrong slug fails closed: cadmin refuses the whole proposal.

## 4. The envelope

```json
{
  "v": 1,
  "service": "alert-bot-demo",
  "brand": "DEMO",
  "title": "Tighten the daily threshold",
  "note": "Six threshold breaches in five days, all above 5,000; three entities involved.",
  "author": "alert-bot-demo-mcp",
  "created_at": "2026-09-30T09:15:00Z",
  "changes": [ ... ]
}
```

`service` and `brand` are checked before anything is rendered. `brand` is verified against the
service's own `brand_id` and the live rows; a mismatch is a hard refusal.

## 5. A change

```json
{
  "id": "6a99f6a7157bcb95952e5b17",
  "name": "Threshold Breach 5000 24h",
  "op": "upsert",
  "code": "threshold_breach",
  "reason": "Fired 6x in 5 days (list_alert_journal); every event was above 5,200, so 5,000 catches the same entities with fewer repeats at 5,500.",
  "set": { "config": { "threshold": 5500 } }
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | to change or delete | Mongo ObjectId, 24 hex. **Present means update, absent means create.** |
| `op` | no | `"upsert"` (default) or `"delete"`. A delete needs an `id`. |
| `code` | on create | `checker_code`. On an update a **guard**: a different live code blocks the row. |
| `name` | no | The alert's name *as you saw it*. A guard, never identity. |
| `reason` | yes here | Evidence, not intent. The tool refuses a change without one. |
| `set` | on upsert | The fields to change. Partial. |

### `set` semantics — the part that bites

| Key | Behaviour |
|---|---|
| *absent* | left alone (on create: the default) |
| `checker_name` | renames the alert |
| `description`, `cron` | set; `null` clears |
| `enabled`, `frequency_minutes`, `max_instances` | set directly |
| `channels`, `segments`, `regions` | **replace the whole list**; `[]` clears it |
| `config` | **merges per key**; a key set to `null` is removed |

Two traps: a threshold belongs inside `config`, not at the top of `set`; and `"channels": []`
clears the list — "leave alone" is omitting the key.

### How cadmin classifies each row

| Situation | Row |
|---|---|
| no `id`, `upsert` | **create** |
| `id` found, `upsert`, something differs | **update** — field-by-field diff |
| `id` found, `upsert`, nothing differs | **no change** — not applied |
| `id` found, `delete` | **delete** — never pre-ticked |
| `id` missing, `delete` | **already gone** |
| `id` missing, `upsert` | **stale** — blocked |
| `code` disagrees with the live alert | **conflict** — blocked |

## 6. Writing a proposal worth approving

- **Evidence in `reason`, not intent.** Cite what you read: `list_alert_journal` counts,
  `list_alerts` values, `describe_checker_type` requirements.
- **One concern per change.** A row that retunes a threshold AND re-routes channels cannot be
  approved or rejected as a unit. Split it.
- **Set only what you are changing.**
- **Nothing to change, no link.**
- **`validate_segments` before anything goes into `set.segments`.**

## 7. Handing the link over

Say what the reviewer is approving, post the link as plain re-pastable text, and never wrap it in
anything that might strip the `#`. Apply is **not transactional**: rows go one at a time.

## 8. Self-check

- [ ] `service` is the slug from `granted_services`, `brand` matches it in upper case.
- [ ] Every update or delete carries a 24-hex `id`; every create carries `code` and `set.checker_name`.
- [ ] Every `set` key is one of the ten cadmin applies; knobs sit inside `config`.
- [ ] No `[]` that was meant as "leave alone".
- [ ] Every change has an evidence-based `reason` and one concern.
- [ ] Every row changes at least one live value.
- [ ] The link was printed whole.
