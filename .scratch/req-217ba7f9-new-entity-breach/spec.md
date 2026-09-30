# REQ-217BA7F9 — New alert: big first deposit from a fresh account on TEST1

Status: ready-for-human

## The request as received

- `request_id`: REQ-217BA7F9
- `requested_by`: general-dev-team
- `capybara_task_id`: 8
- `source`: capybara
- `application`: Notification Service
- `brands`: TEST1
- `sent_at`: 2026-09-30T14:46:38Z
- `title`: [Notification Bot] New alert: big first deposit from a fresh account on TEST1

`description`, verbatim:

> We need a new alert on brand TEST1: a player makes a first deposit of 1,000 EUR or more within 24 hours of registration. This is a typical pattern of bonus abuse and stolen cards, and today nobody sees it until the withdrawal.
>
> Trigger. First successful deposit ≥ 1,000 EUR (EUR equivalent) and account age < 24 hours.
>
> Message. Player ID, registration time, deposit amount and currency, payment method.
>
> Channel. #demo-alerts.

## What the request asks for

- **(a) Subject** — the entity (one account; `entity_id`). Not the brand.
- **(b) Trigger** — the entity's **first** successful deposit reaches 1,000 EUR while the account is
  **less than 24 hours old**, counted from its registration.
- **(c) Numbers** — threshold 1,000 EUR (EUR equivalent); account age window 24 hours. No other
  number is stated: cadence and deduplication TTL are silent.
- **(d) Audience** — nothing stated: no segment, no region, no VIP restriction. Both VIP flags stay
  true and `segments` / `regions` stay unset (no gate), which is the contract's "no restriction".
- **(e) Destination** — `#demo-alerts` (stated).
- **(f) Cadence** — not stated. Taken from the brand's existing `threshold_breach` rows, which run
  at `frequency_minutes: 15` (`list_alerts(brand="TEST1")`); echoed to the requester as a question.

Message content the request names: player id, registration time, deposit amount **and currency**,
payment method.

## Verdict: new

`list_checker_types()` returns four types; only `threshold_breach` is close, and it does not match:

| Requirement | `threshold_breach` (`describe_checker_type`) | Verdict |
| --- | --- | --- |
| first deposit | sums **every** successful amount in the window; no notion of a first event | not expressible |
| account age < 24h | no registration moment anywhere in its config or in `Event` | not expressible |
| ≥ 1,000 | `threshold` | knob exists |
| `#demo-alerts` | `channels` | row field |

`activity_drop` is brand-level (cohort volume), `status_stuck` is about a non-final status,
`heartbeat` is the service's own dependencies. None of their triggers is (b).

The two missing conditions are not a gate or a knob bolted onto an existing trigger — they change
what the checker aggregates (one event, the earliest of its kind, rather than a rolling sum) and add
an input the event stream did not carry. That is a different trigger, so this is **new**, not
**extend**.

Evidence read: `list_checker_types()`, `describe_checker_type("threshold_breach")`,
`describe_alert_contract`, `list_alerts(brand="TEST1")`, `list_alert_journal(brand="TEST1")`.
TEST1's live rows are `Heartbeat`, `Threshold Breach 5000 24h`, `Threshold Breach 1000 1h Premium`
(disabled, Premium-only, 1h rolling sum), `Activity Drop 50% 30m`, `Status Stuck 120m EU` — none of
them fires on (b). The journal confirms it: every `threshold_breach` event carries a cumulative
`total` (5,200 / 5,700 / 6,100 / 5,320 / 5,050) with no registration or first-event evidence.

New checker code: **`new_entity_breach`**.

## Completeness gate

Every product decision the verdict needs is in the request: the threshold (1,000), the window
(24h), the channel (`#demo-alerts`), and an audience that is explicitly unrestricted. The trigger is
specific enough for WHEN/THEN scenarios: which events count (kind `inflow`, status `success`), the
condition (first such event ≥ threshold), the window (registration within `account_age_hours` of the
run), and the entity (the account, which is also the deduplication scope).

Two values the request is silent about, taken from existing rows and named in the proposal `reason`
and in the callback questions:

- `frequency_minutes: 15` — the cadence of TEST1's live `Threshold Breach 5000 24h` row.
- deduplication TTL — no new knob: the TTL is `account_age_hours`, exactly as `threshold_breach`
  suppresses for its own window. An entity that is no longer new can never re-trigger, so one
  account yields at most one alert event.

## Domain vocabulary and the abstract event stream

`CONTEXT.md` and ADR-0001 keep this demo's events abstract: the checkers say *entity*, never
*player*, and the event kinds are `inflow` / `outflow` / `session`, never *deposit*. This change
keeps that: a deposit is an `inflow` event, a registration is a `registration` event, and the two
kinds are knobs (`event_kind`, `registration_event_kind`), not constants.

The message the request asks for needs two attributes the abstract `Event` did not carry: the
currency the amount was reported in, and the payment method. Both are added as optional descriptive
fields on `Event`:

- `currency: str | None` — the currency the amount was reported in; `amount` stays the single-unit
  (EUR-equivalent) figure the threshold is compared against, which is what "EUR equivalent" in the
  request means.
- `source: str | None` — where the event came from; the abstract stand-in for the payment method,
  named the way `inflow` stands in for a deposit and `entity` for a player.

This touches ADR-0001's list of abstract event attributes but does not contradict it: both fields
are descriptive strings on the existing `Event`, they default to `None`, and no data source is
introduced. Called out here and in the pull request rather than done silently.

## Seams

Tested exactly where `tests/test_checker_*_unit.py` test today — `check(events)` over a list of
`checkers.base.Event` built with a fixed clock (`NOW`), one test per WHEN/THEN scenario of the spec:

- **Trigger** — first successful event of `event_kind` at/above `threshold`, for an entity whose
  `registration_event_kind` event falls inside the run's `account_age_hours` window.
- **Non-triggers** — registration older than the window; no registration event at all; a later,
  larger event when the first one was below the threshold; unsuccessful events; an entity with no
  event of `event_kind`.
- **Gates** — through the row's `segments` / `regions` and the `config` VIP flags, judged on the
  first-deposit event, as `test_checker_threshold_breach_unit.py::test_segment_and_region_gates`
  does.
- **Deduplication** — through a shared `checkers.base.Suppression`, asserting the key
  `TEST1:new_entity_breach:<entity_id>` and a TTL of `account_age_hours`.
- **Config hooks** — `REQUIRED_CONFIG_KEYS`, `CONFIG_VALUE_BOUNDS`, `config_warnings` asserted
  directly on the class, as every other checker's test does.
- **Registry** — `tests/test_checkers_registry_unit.py` guards the enum, the class, the catalogue
  row and the spec; its `test_sample_events_drive_every_catalogue_row` is extended with the new row.

## Spec of record

`openspec/changes/add-new-entity-breach-checker/` — proposal, design, tasks and the delta spec at
`specs/checkers/new-entity-breach/spec.md`. The main spec lands in the same commit at
`openspec/specs/checkers/new-entity-breach/spec.md`, which is the exact path `list_checker_types`
and `describe_checker_type` read.

The OpenSpec CLI is not installed in this environment (`command -v openspec` is empty), so
`openspec new change` / `openspec validate --specs` were not run; `CLAUDE.md` prescribes the
file-based fallback, and the change directory follows the format the existing specs use.

## Configuration proposed for TEST1

One row, proposed through a cadmin review link, applied by a human **after this pull request is
merged and deployed** — the deployed server does not know the code yet.

```json
{
  "op": "upsert",
  "code": "new_entity_breach",
  "name": "New Entity Breach 1000 24h",
  "reason": "REQ-217BA7F9 (general-dev-team, capybara task 8): TEST1 has no rule for a first large amount from a fresh account. list_alerts(brand=TEST1) shows the closest row, 'Threshold Breach 5000 24h', sums every successful amount over a rolling day; list_alert_journal(brand=TEST1, checker_code=threshold_breach) confirms every event it raised was a cumulative total (5,200 / 5,700 / 6,100), never a first amount on a new account. describe_checker_type('threshold_breach') has no knob for the first event or for account age, so this is the new new_entity_breach checker. Threshold 1,000 and the 24h account-age window are the requester's; frequency_minutes 15 is taken from the brand's existing Threshold Breach 5000 24h row and is flagged back as a question.",
  "set": {
    "checker_name": "New Entity Breach 1000 24h",
    "description": "An entity's first successful inflow reaches 1,000 within 24 hours of its registration.",
    "enabled": true,
    "frequency_minutes": 15,
    "max_instances": 1,
    "channels": ["#demo-alerts"],
    "config": {
      "account_age_hours": 24,
      "threshold": 1000,
      "event_kind": "inflow",
      "registration_event_kind": "registration",
      "check_vip_users": true,
      "check_non_vip_users": true,
      "mentions": {}
    }
  }
}
```

Envelope: `service: notification-bot-test1` (the `slug` of TEST1's entry in
`list_clusters().granted_services`), `brand: TEST1`, `title` = the request title, `note` = the
request id, `requested_by` and `capybara_task_id`.

Before enabling, the brand's Notification Bot Slack app must be a member of `#demo-alerts`: a
missing membership fails silently.

## Comments

- 2026-09-30 — Opened by the `alert_config.requested` automation for REQ-217BA7F9. Every decision a
  skill would normally put to a person is recorded above: the seams, the verdict, the two values
  taken from existing rows, and the ADR-0001 note. Nothing is left to confirm before implementation.
- 2026-09-30 — Reviewed against `origin/main` on both axes with this file as the spec. Acted on:
  the stale alert-type list in `CLAUDE.md`; a missing `CONFIG_BOUND_REASONS` entry for `threshold`;
  `proposal.md` / `tasks.md` not declaring the documentation and row-count edits; a
  `registration_event_kind: null` row that ran as same-kind but returned no warning (the fallback is
  now one classmethod both paths call); the duplicated earliest-per-entity loop (one
  `_earliest_per_entity(events, keep)`); the names `_registration_moments` and `first`; and three
  missing tests — the >168 rejection, the tie-break rule, and the registration's status being
  ignored. Left as-is and named in the pull request: `amount` + `currency` as two primitives rather
  than one Money type, which the flat `Event` and ADR-0001 argue for keeping.
