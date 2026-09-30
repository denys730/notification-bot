# REQ-D950AF09 — first successful event above a threshold from a freshly registered entity

Status: ready-for-agent

## The request as received

- `request_id`: `REQ-D950AF09`
- `requested_by`: `general-dev-team`
- `capybara_task_id`: `14`
- `source`: `capybara`
- `application`: Notification Service
- `brands`: `TEST1`
- `sent_at`: `2026-09-30T16:47:55Z`
- `title`: `[Notification Bot] New alert: big first deposit from a fresh account on TEST1`

`description`, verbatim:

> We need a new alert on brand TEST1: a player makes a first deposit of 1,000 EUR or more within 24 hours of registration. This is a typical pattern of bonus abuse and stolen cards, and today nobody sees it until the withdrawal.
> Trigger. First successful deposit ≥ 1,000 EUR (EUR equivalent) and account age < 24 hours.
> Message. Player ID, registration time, deposit amount and currency, payment method.
> Channel. #demo-alerts.

## What was asked for

- **(a) Entity** — the entity (a player account), not the brand. The alert event is about one
  `entity_id`, which is also the deduplication scope.
- **(b) Trigger** — an entity's FIRST successful inflow event reaches 1,000 (EUR equivalent) and the
  entity was registered less than 24 hours before that event.
- **(c) Numbers** — threshold `1000`; maximum entity age `24h`. Not stated: the run cadence and the
  suppression TTL (see "Values not in the request").
- **(d) Audience** — none stated. No segment gate, no region gate, both VIP flags left on: the rule
  covers every entity of the brand.
- **(e) Destination** — `#demo-alerts`.
- **(f) Cadence** — not stated.

Message fields the request names, and where each comes from:

| Field asked for | Where it comes from |
| --- | --- |
| Player ID | `AlertEvent.entity_id` |
| registration time | the entity's registration event, in the alert text and in `context.registered_at` |
| deposit amount | `Event.amount` — the demo carries amounts as a plain number in a single unit, so it is already the EUR equivalent; there is no FX conversion anywhere in this codebase and none is being added |
| currency | `Event.currency`, optional, quoted when the event carries it |
| payment method | `Event.payment_method`, optional, quoted when the event carries it |

## Verdict: new

A new checker, `first_event_breach`.

Evidence:

- `list_checker_types()` returns `activity_drop`, `heartbeat`, `status_stuck`, `threshold_breach`.
  No purpose mentions the entity's age or its first event.
- `describe_checker_type("threshold_breach")` — the nearest candidate — triggers on an entity's
  successful amounts **summed over a rolling `monitoring_window_hours`**. It has no knob for the age
  of the entity and no notion of a first event: a row with `threshold: 1000` would fire for a
  five-year-old account whose tenth small inflow tips the sum over 1,000. That is a different
  trigger, not a restriction of this one, so extending it would change what the existing rows on
  every brand mean.
- `status_stuck` triggers on a non-final status, `activity_drop` on brand-level volume, `heartbeat`
  on the service's own dependencies. None matches (b).
- `list_alerts(brand="TEST1")` — five rows: `Heartbeat`, `Threshold Breach 5000 24h`,
  `Threshold Breach 1000 1h Premium` (disabled, Premium-only, one-hour sum), `Activity Drop 30% 15m`,
  `Status Stuck 120m EU`. None of them raises this situation; the 1,000 row is a one-hour **sum**
  restricted to `Business Premium (34)` VIPs, not a first event from a fresh entity.

So: no existing trigger matches, which is the **new** verdict.

## Values not in the request, and where they come from

| Knob | Value | Source |
| --- | --- | --- |
| `frequency_minutes` | 15 | the cadence of TEST1's own `Threshold Breach 5000 24h` row, the closest per-entity money rule the brand runs |
| `cache_ttl_hours` (dedup TTL) | 24 | the default of `status_stuck`, the other per-entity checker with an explicit TTL knob; it also matches `max_entity_age_hours`, after which the entity can no longer trigger |
| `registration_kind` | `registration` | the checker's own default; the demo event stream is abstract, and a registration is an event like any other |
| `event_kind` | `inflow` | how a deposit is already expressed in this demo — `Threshold Breach 5000 24h` sums `event_kind: "inflow"` |

All four are echoed as questions in the callback, so the requester can correct them before the
review link is applied.

## Spec

The behaviour is specified in the OpenSpec change `add-first-event-breach-checker`
(`openspec/changes/add-first-event-breach-checker/`) and, once applied, in
`openspec/specs/checkers/first-event-breach/spec.md`. Read the requirements and scenarios there
rather than a restatement here.

## Seams

The tests sit exactly where `tests/test_checker_threshold_breach_unit.py` and
`tests/test_checker_status_stuck_unit.py` put theirs, one test per WHEN/THEN scenario of the spec:

- **The trigger** — `FirstEventBreachChecker(row, now=NOW).check(events)` over a list of
  `checkers.base.Event` built with the fixed clock `NOW = 2026-09-30T12:00Z`. No Mongo, no clock
  reading. One test per scenario: amount at the threshold, amount below it, an earlier successful
  event of the same kind (not the first), an earlier failed one (still the first success), the
  registration event missing, the entity too old, the entity exactly at the age limit.
- **The gates** — through the row's `segments` / `regions` and through `config`'s
  `check_vip_users` / `check_non_vip_users`, asserted on the qualifying event; a rejected candidate
  is a suppressed candidate and yields no alert event.
- **Deduplication** — a `Suppression` shared between two checker instances, asserting the key
  `{brand}:first_event_breach:{entity_id}` and that the second run raises nothing inside the TTL.
- **Config hooks** — `REQUIRED_CONFIG_KEYS`, `CONFIG_VALUE_BOUNDS` and `config_warnings(config)`
  called directly on the class, as `tests/test_checkers_registry_unit.py` does.
- **The registry** — the catalogue row `First Event Breach 1000 24h` driven by the sample event
  stream in `tests/test_checkers_registry_unit.py`.

The module's shape follows `checker_threshold_breach.py`, the nearest existing checker: a per-entity
rule that reads its knobs from `config`, applies `audience_check` per entity, deduplicates per
entity, and carries its evidence in `context`.

## Configuration proposal for TEST1

The checker code does not exist on the deployed service yet, so the review link is built with the
stdlib encoder from the `proposing-changes` guide rather than by `propose_alert_changes` (the
deployed server refuses a code it does not know). cadmin applies it only after this PR is merged and
deployed.

```json
{
  "v": 1,
  "service": "notification-bot-test1",
  "brand": "TEST1",
  "title": "[Notification Bot] New alert: big first deposit from a fresh account on TEST1",
  "note": "REQ-D950AF09, requested by general-dev-team, capybara task 14",
  "author": "alert-bot-demo-mcp",
  "created_at": "2026-09-30T16:47:55Z",
  "changes": [
    {
      "op": "upsert",
      "code": "first_event_breach",
      "name": "First Event Breach 1000 24h",
      "reason": "REQ-D950AF09 (general-dev-team, capybara task 14) asks for a first deposit of 1,000 EUR or more within 24 hours of registration on TEST1. list_checker_types() has no checker with that trigger and list_alerts(brand=TEST1) has no row that raises it: Threshold Breach 5000 24h and Threshold Breach 1000 1h Premium both sum amounts over a window and ignore the entity's age, so they fire for long-standing accounts and stay silent on a single fresh-account deposit that never reaches their sum. describe_checker_type(threshold_breach) confirms it has no age or first-event knob. The row configures the new first_event_breach checker this PR adds; frequency_minutes 15 is the cadence of the brand's own Threshold Breach 5000 24h row and cache_ttl_hours 24 is the status_stuck default, both marked as questions to the requester.",
      "set": {
        "checker_name": "First Event Breach 1000 24h",
        "description": "An entity's first successful inflow reaches 1,000 less than 24 hours after registration.",
        "enabled": true,
        "frequency_minutes": 15,
        "max_instances": 1,
        "channels": ["#demo-alerts"],
        "config": {
          "threshold": 1000,
          "max_entity_age_hours": 24,
          "event_kind": "inflow",
          "registration_kind": "registration",
          "cache_ttl_hours": 24,
          "check_vip_users": true,
          "check_non_vip_users": true,
          "mentions": {}
        }
      }
    }
  ]
}
```

`service` is the `slug` of TEST1's entry in `list_clusters().granted_services`
(`notification-bot-test1`), read from the tool, not derived from the brand code.

The review link, built from exactly that JSON and verified to decode back to it byte for byte:

https://cadmin.nextvp.club/s/notification-bot-test1/checkers/review#AY1UTW_bMAz9K4R3WAvYRdI1G5phhxZrj0XXdZcNhSHLtC3EljKJThYU_e8jpbgfK7AtlySiSD2-98j7bJMt53kW0G-MxmyZWUemMVqRcbaoHBWEgeZZnlVe2Zov3F58vZX_ZKiXhB9XzzLg3NEdXOEWVI-ellCZFhrjA0GNaxcMQePdAIq_MHSgtHajJeDMqS4DkLI3F1-Kz6eL2dnl7DQHjz9HxoE1VDto0aJXfVHjhtGpIQet1rtKeQWkwgrmJ1xGjdQ5z4UikNhJjYMrBr3mqPaouFqpiG8cz47fF7PT4t3sdv5-efJhuVh8lzudsi2GbPnjPnNrvjeumSaSiKsFYuyrxA1aKisuqDuBrwaJXcaeLyQG5zEG89lsBscncokPgrN_dAkH_27sEPg7QOO8UPiCV9fAPJcnLr7dAMcH5xG2hjpj-VXo3OiDXPLYmkA-yTXxfgQ9H5a6Q71CX9JujeHgEDoVwDrYH8dqQJ0iIG_alk_YEikzshwOokk-xZKP2d5tU5JXJmAAw7a47UR-19cTOYs9ObHiq2ikbt7BtcfBjAOwmh0E_qEGsQ_3tREwDNDW_JrUMK0VAqhDYA0M7d4GUC3mEJwc7oQ9jET2zrZFIE4ytp0cGWIRPt1BMD0miyr-bdsek3mLybyTArFJiwIlwuZe-SXjBekR3wramwpfkHxAU6t7Bx2CdpahDcLTxCDjFkWj3kX0G6ysq46YKIz0xpx29OlFxrCF1-Z8lJEtEeD6BlRdh4_SC8-W1btyMHbkaYf5AkwqpFXNERTbyN-oLvPotvYvCvq9AlooKIn6MnmPTbgvy7TSGMpAo14xL40ae8qTqIPyK55y7jsOPHuUU6JijzvAH2WysHhy77OJy_-auqTAWory3TP7ZIw0SWHUGkNoxh6MbXpuY5IxDVbPQRH52TyphqLaTyMl4NCqqkdeluRHzLNXDPPKXeTZoH6VxorxdDxKG8diLysnexO3VRqr7E52jkgsPT9ahnMYViqUWinZKYntbHl8wkCi_CsTF3fqKW6fJ7hT8PmZbLiX2qVqkexyY9blyIswTO2lY8u1XoUGgcUSMuwH_tw9_AY

It is deploy-gated: apply it only after this PR is merged and deployed, because the running admin
API rejects a configuration write for a checker code it does not know.

Before the row is enabled, the brand's Notification Bot Slack app has to be a member of
`#demo-alerts`: a missing membership fails silently.

## Comments

- 2026-09-30 — Opened by the `alert_config.requested` automation for REQ-D950AF09. Nobody is on the
  other side of the run, so the open questions above were decided from the brand's own rows and the
  catalogue rather than asked, and each one is echoed in the callback for the requester to confirm.
