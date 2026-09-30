## Purpose

Flags an entity whose FIRST successful event of one kind reaches a threshold while the entity itself
is still new. A cumulative rule cannot see this: one ordinary-looking amount never reaches a daily
total, and what is unusual is not the size but how soon after registration it arrived.

Checker code: `new_entity_breach`. Inherits the configuration, gating, deduplication, routing and
journaling contract in `event-checking`.

## Requirements

### Requirement: A new entity is one whose registration falls inside the monitoring window

The checker reads an entity's registration moment from the EARLIEST event of
`registration_event_kind` it holds for that entity, whatever that event's status. The entity is new
when that moment falls in the monitoring window ending at the current run and starting
`account_age_hours` earlier, both bounds inclusive. An entity the stream holds no such event for has
no known registration moment and is skipped.

#### Scenario: Entity registered inside the window
- **WHEN** an entity's registration event falls inside the window
- **THEN** the entity is new and its first qualifying event is judged

#### Scenario: Entity registered before the window
- **WHEN** an entity's registration event is older than `account_age_hours`
- **THEN** no alert is raised for that entity

#### Scenario: Entity without a registration event
- **WHEN** the stream holds no event of `registration_event_kind` for an entity
- **THEN** no alert is raised for that entity

### Requirement: Only the entity's first successful event of the configured kind is judged

An entity's first qualifying event is the EARLIEST successful event of `event_kind` created at or
after its registration moment. An alert is raised when that event's amount is at least `threshold`.
An entity whose first qualifying event falls short is not revived by a later, larger one, and events
that are not successful never qualify — not even to be first. Two qualifying events sharing the
earliest timestamp are resolved in the order they arrive in the stream.

#### Scenario: First amount at or above the threshold
- **WHEN** a new entity's first qualifying event has an amount of at least `threshold`
- **THEN** an alert is raised for that entity

#### Scenario: First amount below the threshold
- **WHEN** a new entity's first qualifying event is below `threshold` and a later event of the same kind is above it
- **THEN** no alert is raised for that entity

#### Scenario: Event is not successful
- **WHEN** a new entity's earliest event of `event_kind` is pending or failed
- **THEN** it is ignored and the earliest successful one is judged in its place

#### Scenario: Event of another kind
- **WHEN** a new entity's largest event is of a kind other than `event_kind`
- **THEN** it takes no part in the decision

#### Scenario: Event created before the registration moment
- **WHEN** an event of `event_kind` was created before the entity's registration moment
- **THEN** it is not the entity's first qualifying event

### Requirement: New entity breach alert content

The alert names the brand, the entity, the amount with the currency it was reported in, the source
the amount arrived through, the registration moment, how old the entity was when the event arrived,
and the threshold that was applied. Its context carries `amount`, `currency`, `source`, `threshold`,
`registered_at`, `occurred_at`, `age_hours` and `account_age_hours`. An attribute the event does not
carry reads `unknown` in the text and is `null` in the context.

#### Scenario: Alert carries its evidence
- **WHEN** an alert is raised
- **THEN** its context holds `amount`, `currency`, `source`, `threshold`, `registered_at`, `occurred_at`, `age_hours` and `account_age_hours`

### Requirement: New entity breach suppression

After alerting, the entity is suppressed for a number of hours equal to `account_age_hours`. The
suppression outlives the entity's own newness, so one entity yields at most one alert event however
often the checker runs.

#### Scenario: Entity keeps producing events while still new
- **WHEN** an entity that has already alerted produces further events before `account_age_hours` has elapsed
- **THEN** no second alert is raised for that entity

### Requirement: New entity breach configuration

The row's `config` carries:

- `account_age_hours` — required, 1 to 168; how new the entity must be, and the suppression TTL.
- `threshold` — required, at least 0; the first amount that fires.
- `event_kind` — required; the kind of event whose first occurrence is judged.
- `registration_event_kind` — optional, default `registration`; the kind that marks a registration.
- `check_vip_users` / `check_non_vip_users` — the VIP audience gate, judged on the first qualifying event.
- `mentions` — Slack users to mention on the alert.

#### Scenario: Both VIP flags off
- **WHEN** `check_vip_users` and `check_non_vip_users` are both false
- **THEN** the configuration is accepted with a warning that the rule alerts about nobody

#### Scenario: Registration kind judged as the qualifying kind
- **WHEN** `registration_event_kind` and `event_kind` name the same kind
- **THEN** the configuration is accepted with a warning that the registration is its own first qualifying event, so the rule alerts about nobody

#### Scenario: Window longer than retention
- **WHEN** `account_age_hours` is above 168
- **THEN** the write is rejected, because events are kept for 7 days and an older registration is no longer in the stream
