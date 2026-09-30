## Purpose

Flags a brand whose event volume in the current window has fallen well below its own recent
baseline — an outage or a broken integration reads as silence, and silence is what this alert turns
into a signal.

Checker code: `activity_drop`. Inherits the configuration, routing and journaling contract in
`event-checking`. A brand-level checker: its entity is the brand, and the audience gates restrict
the cohort that is counted rather than suppressing a computed alert.

## Requirements

### Requirement: Compare the current window against a per-day baseline

The checker counts events in the window ending now and lasting `window_minutes`, and the events in
the same-length window ending exactly one, two, … `baseline_days` days earlier. The baseline is the
mean of those daily counts. Only events that pass the row's audience gates are counted, in every
window.

#### Scenario: Volume dropped past the threshold
- **WHEN** the current count is at least `drop_percent` percent below the baseline
- **THEN** one alert is raised for the brand

#### Scenario: Volume within tolerance
- **WHEN** the current count is less than `drop_percent` percent below the baseline
- **THEN** no alert is raised

#### Scenario: Baseline too thin to judge
- **WHEN** the baseline averages fewer than `min_baseline_events` events
- **THEN** no alert is raised, whatever the current count

### Requirement: Activity drop alert content

The alert names the brand, the current count, the baseline, the drop in percent and the configured
threshold. Its context carries the window length and the number of baseline days.

#### Scenario: Alert carries its evidence
- **WHEN** an alert is raised
- **THEN** its context holds `current`, `baseline`, `drop_percent`, `threshold_percent`, `window_minutes` and `baseline_days`

### Requirement: Activity drop suppression

After alerting, the brand is suppressed for one window length, so an ongoing quiet period yields
one alert per window.

#### Scenario: Quiet period continues
- **WHEN** the checker runs again inside the window after alerting
- **THEN** no second alert is raised

### Requirement: Activity drop configuration

The row's `config` carries:

- `window_minutes` — required, 5 to 1440.
- `baseline_days` — required, 1 to 7; events are kept for 7 days.
- `drop_percent` — required, 1 to 100.
- `min_baseline_events` — optional, default 20.

#### Scenario: Baseline minimum set very low
- **WHEN** `min_baseline_events` is below 5
- **THEN** the configuration is accepted with a warning that ordinary quiet minutes will read as a drop
