## Purpose

Verifies that the demo service's own dependencies are reachable, so that a silent outage of the
alerting system is itself alerted on. Every other checker can only report a problem while the
service works; this one exists to make the failure of the service visible.

Checker code: `heartbeat`. Inherits the configuration and journaling contract in `event-checking`.
Its audience gates and deduplication do not apply: its subject is the service, not an entity.

## Requirements

### Requirement: Dependency probes

On each run the checker probes the named dependencies in the order given and stops at the first
failure — a later probe cannot be trusted once an earlier dependency is known to be down. A probe
that raises counts as a failure.

#### Scenario: All dependencies are reachable
- **WHEN** every probe succeeds
- **THEN** the run completes without alerting

#### Scenario: A dependency is unreachable
- **WHEN** a probe fails or raises
- **THEN** a service alert naming that dependency is raised and no later probe runs

### Requirement: Failures are service alerts

Heartbeat failures are SERVICE alerts for the brand's monitoring channel, never for an alert
channel — an outage is an operational signal for whoever runs the bot, not a business alert.

#### Scenario: Alert is flagged as a service alert
- **WHEN** the heartbeat raises an alert
- **THEN** it is marked as a service alert and names the failing dependency in its context

### Requirement: Heartbeat configuration

The row's `config` is empty: this checker has no thresholds, windows or audience knobs. Only the
shared scheduling and enablement fields apply, and `check()` over events raises nothing.

#### Scenario: Events are not an input
- **WHEN** the checker is handed a list of events
- **THEN** it raises no alert from them
