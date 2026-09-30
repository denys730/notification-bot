## Purpose

Flags a freshly registered entity whose FIRST successful event of a kind already reaches a
threshold. A cumulative rule cannot see this: one event is all there is, and what makes it worth
announcing is not the size alone but the size arriving from an entity that registered hours ago.

Checker code: `first_event_breach`. Inherits the configuration, gating, deduplication, routing and
journaling contract in `event-checking`.

## Requirements

### Requirement: Alert on an entity's first successful event of a kind

The checker SHALL consider, per entity, the earliest successful event whose kind equals
`event_kind`, and SHALL raise an alert event for that entity when the event's amount is at least
`threshold` and the entity passes the age requirement below. Later events of that kind SHALL NOT be
considered, and an event that is not successful SHALL NOT be considered — an earlier failed or
pending event therefore leaves the earliest successful one as the first. Events of any other kind
SHALL NOT be considered. The audience gates SHALL be judged on that first successful event.

#### Scenario: First successful event reaches the threshold
- **WHEN** an entity's earliest successful event of `event_kind` has an amount of at least `threshold` and the entity is young enough
- **THEN** an alert event is raised for that entity

#### Scenario: First successful event falls short of the threshold
- **WHEN** an entity's earliest successful event of `event_kind` has an amount below `threshold`
- **THEN** no alert event is raised for that entity, even if a later event of the same kind is larger

#### Scenario: An earlier unsuccessful event does not take the place of the first
- **WHEN** an entity's earliest event of `event_kind` failed and a later one succeeded above `threshold`
- **THEN** the later successful event is treated as the entity's first and an alert event is raised

#### Scenario: Events of another kind are ignored
- **WHEN** an entity's earlier events are of a kind other than `event_kind`
- **THEN** they neither trigger the checker nor stop the first event of `event_kind` from being the first

#### Scenario: Entity outside the audience
- **WHEN** the first successful event belongs to an entity the row's gates exclude
- **THEN** the candidate is suppressed and no alert event is raised

### Requirement: The entity SHALL be younger than the configured age when the event arrives

The entity's registration is the earliest event of kind `registration_kind` the checker sees for it.
The entity's age is measured from that registration to the first successful event of `event_kind`,
not to the clock of the run, so a run that happens later still reports an event that arrived in
time. The alert event SHALL be raised only when that age is strictly below `max_entity_age_hours`.
When no registration event is present for the entity the age cannot be established and the candidate
SHALL be suppressed, and so SHALL a candidate whose event predates its own registration.

#### Scenario: Entity registered inside the age limit
- **WHEN** the first successful event of `event_kind` is less than `max_entity_age_hours` after the entity's registration event
- **THEN** the entity passes the age requirement

#### Scenario: Entity registered exactly at the age limit
- **WHEN** the first successful event of `event_kind` is exactly `max_entity_age_hours` after the entity's registration event
- **THEN** no alert event is raised, because the age must be strictly below the limit

#### Scenario: Entity older than the age limit
- **WHEN** the first successful event of `event_kind` is more than `max_entity_age_hours` after the entity's registration event
- **THEN** no alert event is raised for that entity

#### Scenario: No registration event for the entity
- **WHEN** the events hold no event of kind `registration_kind` for an entity that otherwise qualifies
- **THEN** no alert event is raised, because the entity's age is unknown

#### Scenario: Run happens long after the event
- **WHEN** the qualifying event arrived inside the age limit but the run's clock is days later
- **THEN** the alert event is still raised, because the age is measured at the event

#### Scenario: Event predates the registration
- **WHEN** the first successful event of `event_kind` is older than the entity's registration event
- **THEN** no alert event is raised, because the event is not a first event *after* registration whatever a clock skew or a backfilled registration says

### Requirement: First event breach alert content

The alert SHALL name the brand, the entity, the amount of the first event, the moment the entity
registered, the age of the entity at that event in hours, and the threshold that was applied. Its
context SHALL carry `amount`, `threshold`, `event_kind`, `entity_age_hours`, `max_entity_age_hours`,
`registered_at` and `event_at`. When the event carries a currency or a payment method, each SHALL
appear in the alert text and in the context; an event without one SHALL produce an alert that simply
omits it, in the text and in the context alike.

#### Scenario: Alert carries its evidence
- **WHEN** an alert event is raised
- **THEN** its context holds `amount`, `threshold`, `event_kind`, `entity_age_hours`, `max_entity_age_hours`, `registered_at` and `event_at`, and its text names the entity and the moment it registered

#### Scenario: Event carries a currency and a payment method
- **WHEN** the first successful event has a currency and a payment method
- **THEN** the alert text names both and the context carries them as `currency` and `payment_method`

#### Scenario: Event carries neither a currency nor a payment method
- **WHEN** the first successful event has neither
- **THEN** the alert text names neither and the context carries no `currency` and no `payment_method` key

### Requirement: First event breach suppression

After alerting about an entity, the checker SHALL suppress further alert events about that entity
for `cache_ttl_hours` hours, defaulting to 24.

#### Scenario: Same entity inside the TTL
- **WHEN** the checker runs again over the same events before `cache_ttl_hours` has elapsed
- **THEN** no second alert event is raised for that entity

### Requirement: First event breach configuration

The row's `config` carries:

- `threshold` — required, at least 0; the amount the first successful event must reach.
- `max_entity_age_hours` — required, 1 to 168; the entity must be younger than this at that event.
- `event_kind` — required; the kind of event the rule watches.
- `registration_kind` — optional, default `registration`; the kind of event that marks the entity's
  registration.
- `cache_ttl_hours` — optional, default 24; the suppression TTL.
- `check_vip_users` / `check_non_vip_users` — the VIP audience gate.
- `mentions` — Slack users to mention on the alert.

#### Scenario: Both VIP flags off
- **WHEN** `check_vip_users` and `check_non_vip_users` are both false
- **THEN** the configuration is accepted with a warning that the rule alerts about nobody

#### Scenario: Watched kind is the registration kind
- **WHEN** `event_kind` and `registration_kind` are the same string
- **THEN** the configuration is accepted with a warning that the registration event is itself the first watched event, so the rule fires on registration

#### Scenario: Suppression shorter than the age limit
- **WHEN** `cache_ttl_hours` is shorter than `max_entity_age_hours`
- **THEN** the configuration is accepted with a warning that the same first event alerts again while the entity is still inside the age limit

#### Scenario: Age limit longer than retention
- **WHEN** `max_entity_age_hours` is above 168
- **THEN** the write is rejected, because events are kept for 7 days and the registration event of an older entity is no longer there to read
