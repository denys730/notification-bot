## Purpose

Flags an entity whose SUCCESSFUL amounts, summed over a rolling window, reach a threshold. It
catches cumulative activity that no single event would reveal — many mid-sized events reach the
same exposure as one large one, and this alert makes that visible.

Checker code: `threshold_breach`. Inherits the configuration, gating, deduplication, routing and
journaling contract in `event-checking`.

## Requirements

### Requirement: Aggregate successful amounts per entity over a rolling window

The checker sums each entity's successful events whose creation timestamp falls in the window
ending at the current run and starting `monitoring_window_hours` earlier, both bounds inclusive.
When `event_kind` is set, only events of that kind participate. An entity's audience gates are
judged on its latest event in the window.

#### Scenario: Entity's amounts total at or above the threshold
- **WHEN** an entity's successful amounts in the window sum to at least `threshold`
- **THEN** an alert is raised for that entity

#### Scenario: Event is not successful
- **WHEN** an entity's events in the window are pending or failed
- **THEN** they do not count towards the sum

#### Scenario: Event is outside the window
- **WHEN** an event was created before the window started
- **THEN** it is excluded from the entity's total

#### Scenario: Total falls short of the threshold
- **WHEN** an entity's total is below `threshold`
- **THEN** no alert is raised for that entity

### Requirement: Threshold breach alert content

The alert names the brand, the entity, the total, the window length in hours, the threshold that
was applied, and the number of events that made up the total. Its context carries the window's
start and end.

#### Scenario: Alert carries its evidence
- **WHEN** an alert is raised
- **THEN** its context holds `total`, `threshold`, `window_hours`, `events`, `window_start` and `window_end`

### Requirement: Threshold breach suppression

After alerting, the entity is suppressed for a number of hours equal to `monitoring_window_hours`,
so a single sustained run of events produces one alert per window rather than one per checker run.

#### Scenario: Entity keeps producing events inside the window
- **WHEN** an entity that has already alerted produces further events before the window elapses
- **THEN** no second alert is raised for that entity

### Requirement: Threshold breach configuration

The row's `config` carries:

- `monitoring_window_hours` — required, 1 to 168; the rolling window length, also the suppression TTL.
- `threshold` — required, at least 0; the sum that fires.
- `event_kind` — optional; restrict the sum to events of one kind.
- `check_vip_users` / `check_non_vip_users` — the VIP audience gate.
- `mentions` — Slack users to mention on the alert.

#### Scenario: Both VIP flags off
- **WHEN** `check_vip_users` and `check_non_vip_users` are both false
- **THEN** the configuration is accepted with a warning that the rule alerts about nobody

#### Scenario: Window longer than retention
- **WHEN** `monitoring_window_hours` is above 168
- **THEN** the write is rejected, because events are kept for 7 days
