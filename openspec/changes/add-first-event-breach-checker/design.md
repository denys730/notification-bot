# Design

## Context

See proposal.md — Why. The constraints that shape the approach are the ones in `CLAUDE.md` and
`openspec/specs/event-checking/spec.md`: a checker is a pure function of a row, a clock and a list
of `Event`s; `Event` is deliberately abstract (`kind` and `status` are free strings, `amount` is a
number in a single unit); the gates, the deduplication and the validation hooks live in
`BaseChecker`; and nothing here schedules, converts currency or delivers anything.

Two facts of the request have to land on that shape. "Deposit" is an event of a configured kind —
the demo already expresses it as `event_kind: "inflow"` in `Threshold Breach 5000 24h`. "Account
age" needs a registration moment, and `Event` carries no account-creation timestamp.

## Goals / Non-Goals

**Goals:**

- A trigger that reads as one sentence: the entity's first successful event of a kind, above a
  threshold, from an entity that registered less than N hours before it.
- Every value an operator could disagree with is a knob in `config`, never a constant in the code.
- The alert carries the fields REQ-D950AF09 asks for, as far as the demo's event shape holds them.

**Non-Goals:**

- Currency conversion. `amount` is a number in a single unit, so the threshold is already the
  EUR-equivalent the request asks for; there is no FX anywhere in this codebase and this change adds
  none. `currency` is descriptive, quoted in the alert, never compared against the threshold.
- Any notion of an account record. The registration stays an event like any other.
- Creating a configuration row on a running brand — that arrives through the cadmin review link.

## Decisions

### A new checker, not a knob on `threshold_breach`

`threshold_breach` triggers on a SUM over a rolling window. Adding "first event only" and "entity
younger than N" to it would make one class carry two triggers and would change the meaning of the
rows every brand already runs (the two TEST1 rows, the catalogue rows). Rejected in favour of a
separate `first_event_breach` class, which is also what the "adding a checker" list in `CLAUDE.md`
is written for.

### Registration is the earliest event of a configured kind

Alternatives considered:

1. A new `registered_at` field on `Event`, set by whatever produces events. Rejected: it makes every
   event carry an entity attribute, which is a different thing from "one thing that happened", and
   every existing producer would have to fill it for the checker to work.
2. The entity's earliest event of any kind. Rejected: it silently reads a stream that starts
   mid-life as a fresh registration, which is exactly the false positive this alert must not make.
3. **Chosen:** the earliest event of kind `registration_kind` (default `registration`). It keeps
   `Event` abstract, it is configurable per row, and its failure mode is the safe one — no
   registration event means the age is unknown and the candidate is suppressed rather than alerted
   on. The `max_entity_age_hours` bound of 168 keeps that honest: within the 7-day retention, the
   registration event of a qualifying entity is always still in the stream.

### Age is measured at the event, not at the run clock

The request says "within 24 hours of registration" — a property of the deposit, not of the moment
someone happens to look. Measuring against `self.now` would drop the alert entirely if the checker
ran 25 hours after a registration, which is the alert failing exactly when it matters. The window
helpers on `BaseChecker` measure against the run clock, so this checker does its own subtraction;
that is the one place it departs from `checker_threshold_breach.py`.

### `currency` and `payment_method` are optional fields on `Event`

The request names them as message content. They are descriptive strings with no effect on the
trigger, so they are optional with a `None` default: every existing construction of `Event` keeps
working, no existing checker reads them, and the alert quotes them only when they are there.

### The threshold is inclusive, the age limit is exclusive

"≥ 1,000" and "< 24 hours", straight from the request. Both boundaries get a scenario in the spec
so neither is left to a reader's assumption.

## Risks / Trade-offs

- [An entity whose registration event has aged out of the stream never alerts] → The age bound is
  capped at 168 hours, below the 7-day retention, so any entity young enough to qualify still has
  its registration event. Stated in `CONFIG_BOUND_REASONS`.
- [A stream that carries no registration events at all makes the rule silent, and silence looks like
  "nothing happened"] → `registration_kind` is a knob rather than a constant, the default is
  documented in the spec, and `config_warnings` calls out the one configuration that turns the rule
  into a registration alarm (`event_kind` equal to `registration_kind`).
- [`cache_ttl_hours` shorter than `max_entity_age_hours` re-alerts on the same first event] → a
  config warning, following `status_stuck`, which reports the same class of mistake.
- [Two optional fields on a frozen dataclass widen the shared event shape] → both default to `None`
  and nothing existing reads them; the registry test and the full suite guard the rest.

## Migration Plan

No data migration: no stored row changes and no existing row is read differently. The new alert type
is inert until a row of it exists. Rollback is reverting the commit — with no row of the new code in
any brand, nothing else refers to it. TEST1's row is applied by a human through the cadmin review
link in the PR, only after this ships; that ordering matters, because the deployed admin API rejects
a config write for a checker code it does not know.
