## Purpose

Defines the contract every checker in alert-bot-demo obeys: how a checker is configured per brand,
how its configuration is validated on write, which audience gates it applies before alerting, how
repeat alerts are suppressed, and how an alert is routed and journaled. Individual checker
specifications under `checkers/` describe only what makes each alert distinct and inherit everything
stated here.

This is a demo contract. A checker here is a pure function of a configuration row, a clock and a
list of events: nothing schedules it and nothing delivers what it returns. The shape — per-row
configuration, validation hooks, gates, deduplication, journaling — is a production one; the
pipeline behind it is deliberately absent.

## Requirements

### Requirement: Per-brand checker configuration

Every checker instance is driven by one `checkers_configs` row in the shared `alert_bot_system`
database, keyed uniquely by `(brand, checker_name)`. A row carries the scheduling fields
(`frequency_minutes`, `cron`, `max_instances`, `enabled`), the routing fields (`channel`,
`channels`), the audience fields (`segments`, `regions`), and a free-form `config` object holding
the checker-specific knobs.

One checker class MAY back several rows on the same brand. Each row is an independent rule with its
own thresholds, window, schedule, and channels.

#### Scenario: Two rules of the same checker on one brand
- **WHEN** a brand has two rows of the same checker code with different thresholds
- **THEN** each evaluates its own threshold, window, dedup TTL, and channels independently

#### Scenario: Duplicate name on one brand
- **WHEN** a row is created with a `checker_name` another row of the same brand already holds
- **THEN** the write is rejected with a validation error naming the clash

### Requirement: Required configuration knobs are declared per checker

Every checker SHALL declare which `config` keys it requires. A key is required when the checker
reads it with no fallback. A key the checker reads with a fallback is NOT required. A checker with
no required knobs declares none, and any `config` object satisfies it — including an empty one.

The rows in the reference catalogue SHALL satisfy the declaration of the checker they configure.

#### Scenario: Checker declares its required knobs
- **WHEN** a checker reads a `config` key with no fallback
- **THEN** that key is listed in its `REQUIRED_CONFIG_KEYS`

### Requirement: A configuration write missing a required knob is rejected

A `config` object supplied on create or update replaces the stored one in full. The admin API SHALL
reject a write whose `config` omits any key the target checker requires, naming every missing key.
A request that carries no `config` at all is not validated, which keeps an already-incomplete row
editable and therefore repairable.

#### Scenario: Create omits a required knob
- **WHEN** a row is created for a checker and its `config` lacks a required key
- **THEN** the write is rejected with HTTP 400 and the message names the missing key

#### Scenario: Update without a config object
- **WHEN** an update names other fields but not `config`
- **THEN** the stored `config` is untouched and no required-key check runs

### Requirement: Declared value bounds on configuration knobs

A checker MAY declare an inclusive admissible range for a required knob, with a one-sentence reason
that says why the range is what it is. The admin API SHALL reject a write whose value falls outside
the range, quoting the value, the range and the reason. A value with no numeric reading is not a
range violation.

#### Scenario: Window longer than retention
- **WHEN** a write sets a bounded knob above its maximum
- **THEN** the write is rejected with HTTP 400 naming the knob, the value, the admissible range and the reason

### Requirement: Configuration warnings on an accepted write

A checker MAY report advice about a legal-but-surprising combination of values through
`config_warnings`. The admin API returns those messages as `warnings` on a successful create or
update and never rejects on them. A hook that raises yields no warnings.

#### Scenario: Audience emptied by both VIP flags
- **WHEN** a write sets both `check_vip_users` and `check_non_vip_users` to false on a player-targeted checker
- **THEN** the write succeeds and the response's `warnings` says the rule alerts about nobody

### Requirement: Brand isolation

A checker evaluates one brand's rows only, and a row's `brand` is the upper-cased brand code. The
admin API scopes every read and update by the `X-Brand` header, so a row of another brand is not
listed, fetched by list, or updated through it.

#### Scenario: Update addressed to the wrong brand
- **WHEN** an update names a row id that belongs to another brand
- **THEN** the API answers 404 and changes nothing

### Requirement: VIP audience gate

A player-targeted checker consults `check_vip_users` and `check_non_vip_users` inside `config`,
both defaulting to true. A VIP entity passes when `check_vip_users` is true; a non-VIP entity passes
when `check_non_vip_users` is true.

#### Scenario: VIP entity on a non-VIP-only rule
- **WHEN** `check_vip_users` is false and the entity is VIP
- **THEN** no alert is raised for that entity

### Requirement: Segment audience gate

A row's `segments` is an optional allow list of `{segmentation_id}__{value}` entries. When set and
non-empty, a player-targeted checker alerts only for an entity that currently belongs to at least one
listed segment. Unset or empty means no restriction. Entries take the segment VALUE, never the
display name.

#### Scenario: Entity outside every listed segment
- **WHEN** `segments` is `["Business__34"]` and the entity's segments do not include it
- **THEN** no alert is raised for that entity

### Requirement: Region audience gate

A row's `regions` is an optional allow list of registration regions, matched case-insensitively.
When set and non-empty, a player-targeted checker alerts only for an entity whose region is listed;
a brand-level checker counts only such entities. Unset or empty means no restriction.

#### Scenario: Entity registered elsewhere
- **WHEN** `regions` is `["EU"]` and the entity's region is `LATAM`
- **THEN** no alert is raised for that entity

### Requirement: Alert deduplication

After alerting about an entity, a checker suppresses further alerts about the same entity for a
TTL its own specification names, keyed `{brand}:{checker_code}:{entity_id}`.

#### Scenario: Same entity inside the TTL
- **WHEN** a checker runs again before the entity's TTL has elapsed and the condition still holds
- **THEN** no second alert is raised for that entity

### Requirement: Alert routing

A row's `channels` lists the channels every alert of that row goes to; the first entry is the
primary. A row with no list routes to `channel`; the admin API reports `channels` derived from
`channel` for such a row. A service alert — one about the alerting system itself — goes to the
brand's monitoring channel.

#### Scenario: Older row with a single channel
- **WHEN** a stored row has `channel` set and no `channels`
- **THEN** the admin API returns `channels` as a one-element list holding that channel

### Requirement: Alert journaling

Every alert event sent is recorded in the brand's `alert_journal` with the checker, the entity, the
per-destination deliveries and their outcome (`delivered`, `partial`, `failed`), the free-form
`context` the checker supplied, and a snapshot of the configuration in force. The admin API and the
MCP server expose it read-only; the list omits the message body and the snapshot unless asked.

#### Scenario: One channel refused the message
- **WHEN** one of two deliveries failed
- **THEN** the event's status is `partial` and the failed delivery carries the error
