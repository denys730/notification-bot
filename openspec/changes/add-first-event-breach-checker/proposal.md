# Add the `first_event_breach` checker

## Why

REQ-D950AF09 (requested by `general-dev-team`, capybara task 14) asks brand TEST1 for an alert on a
first deposit of 1,000 EUR or more made less than 24 hours after registration — the shape of bonus
abuse and stolen cards, which today nobody sees until the withdrawal. No checker in the catalogue
raises it: `threshold_breach` sums an entity's amounts over a rolling window and knows nothing about
the entity's age or about which of its events was the first, so it both misses the fresh-account
case below its sum and fires for accounts that are years old.

## What Changes

- A new alert type `first_event_breach`: an entity's FIRST successful event of a configured kind
  reaches a threshold, and the entity's registration event is less than `max_entity_age_hours`
  older than that event.
- `Event` gains two optional descriptive fields, `currency` and `payment_method`, carried through to
  the alert text and context when an event has them. Additive: every existing checker is untouched
  and every existing call site keeps working.
- A reference catalogue row `First Event Breach 1000 24h` so a freshly seeded brand starts with a
  working example, and sample events (a registration and a large first inflow for a new entity) that
  drive it.
- No **BREAKING** change: no existing requirement, knob or alert text is altered.

## Capabilities

### New Capabilities

- `checkers/first-event-breach` — the trigger, the knobs, the alert content and the suppression of
  the new alert type.

### Modified Capabilities

None. `event-checking` states the contract every checker inherits (configuration, gates,
deduplication, routing, journaling) and does not enumerate the fields of an event, so the two new
optional event fields change no requirement there. The new checker inherits that contract unchanged.

## Impact

- `src/constants.py` — `CheckerCodes.FIRST_EVENT_BREACH`.
- `src/checkers/checker_first_event_breach.py` (new), registered in `src/checkers/__init__.py`.
- `src/checkers/base.py` — two optional `Event` fields.
- `src/checkers/catalogue.py`, `src/checkers/sample_events.py` — the reference row and the events
  that exercise it.
- `tests/test_checker_first_event_breach_unit.py` (new); `tests/test_checkers_registry_unit.py` and
  `tests/test_mcp_checker_types_unit.py` learn about the new code.
- `openspec/specs/checkers/first-event-breach/spec.md` — the main spec `list_checker_types` and
  `describe_checker_type` read.
- No configuration row is created anywhere by this change: TEST1's row arrives through the cadmin
  review link, after this ships.
