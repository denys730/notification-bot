## Purpose

Flags an entity whose latest event has sat in a non-final status for longer than allowed — a
request nobody is processing, which is what the affected entity would complain about first.

Checker code: `status_stuck`. Inherits the configuration, gating, deduplication, routing and
journaling contract in `event-checking`.

## Requirements

### Requirement: Judge each entity by its latest event

For each entity the checker takes the event with the latest change time. When that event's status
is one of `pending_statuses` and more than `pending_minutes` have passed since it was created, the
entity is stuck. The audience gates are judged on that event.

#### Scenario: Latest event pending for too long
- **WHEN** an entity's latest event is pending and older than `pending_minutes`
- **THEN** an alert is raised for that entity

#### Scenario: Latest event pending but fresh
- **WHEN** an entity's latest event is pending and younger than `pending_minutes`
- **THEN** no alert is raised

#### Scenario: Latest event is final
- **WHEN** an entity's latest event is successful or failed, whatever came before it
- **THEN** no alert is raised for that entity

### Requirement: Status stuck alert content

The alert names the brand, the entity, the status, how long it has been stuck in minutes, and the
limit. Its context carries the moment the event was created.

#### Scenario: Alert carries its evidence
- **WHEN** an alert is raised
- **THEN** its context holds `status`, `stuck_minutes`, `pending_minutes` and `since`

### Requirement: Status stuck suppression

After alerting, the entity is suppressed for `cache_ttl_hours` (default 24).

#### Scenario: Entity still stuck on the next run
- **WHEN** the checker runs again inside the TTL and the entity is still stuck
- **THEN** no second alert is raised for it

### Requirement: Status stuck configuration

The row's `config` carries:

- `pending_minutes` — required, 1 to 10080; events are kept for 7 days.
- `pending_statuses` — optional, default `["pending"]`.
- `cache_ttl_hours` — optional, default 24; the suppression TTL.
- `check_vip_users` / `check_non_vip_users` — the VIP audience gate.

#### Scenario: TTL shorter than the pending window
- **WHEN** `cache_ttl_hours` in minutes is below `pending_minutes`
- **THEN** the configuration is accepted with a warning that a stuck entity alerts on every run
