# Design — `new_entity_breach`

## Context

The request is written in product terms (player, deposit, registration, currency, payment method);
this repository is deliberately abstract (`CONTEXT.md`, ADR-0001): entities, not players; `inflow`
events, not deposits. The design maps the request onto the existing vocabulary rather than importing
the product one.

| Request | Here |
| --- | --- |
| player | entity (`entity_id`) |
| deposit | a successful event of `event_kind`, `inflow` in the proposed row |
| registration | the earliest event of `registration_event_kind`, `registration` by default |
| 1,000 EUR (EUR equivalent) | `threshold`, compared against `amount`, which is a single-unit figure |
| account age < 24h | `account_age_hours`, the monitoring window the registration must fall in |
| currency, payment method | `Event.currency` and `Event.source` |

## Goals / Non-Goals

- **Goals**: express the trigger with knobs an operator sets per row; keep the checker a pure
  function of a row, a clock and a list of events; reuse the gates, the deduplication and the
  validation hooks from `BaseChecker` unchanged.
- **Non-Goals**: a currency conversion layer (`amount` is already the single-unit figure every other
  checker compares), a registration data source, or any change to how existing checkers behave.

## Decisions

### The registration moment comes from the event stream, not from a new input

A checker reads events and nothing else. Making registration an event of its own kind keeps that
true, keeps `check(events)` the only seam the tests need, and costs no new plumbing. The alternative
— an entity profile passed alongside the events — would be a second input for every checker and a
step towards a data source ADR-0001 rules out.

The registration event's status is not examined. The demo stream carries one registration per
entity; insisting on `success` would silently drop entities whose registration arrived with any
other status and make the age gate unexplainably quiet.

### Two conditions, not one

The registration must fall inside the run's window (`now - account_age_hours … now`), AND the first
qualifying event must be at or after the registration moment. Together those two give the request's
"first deposit … within 24 hours of registration" without a third comparison: an event that is after
the registration and no later than the run is necessarily inside the same 24 hours. Bounding the
registration by the RUN's clock, rather than only measuring deposit-minus-registration, also keeps
the checker from alerting days later on an account that was new at the time — events are kept for
seven days, so that stale alert is otherwise reachable.

### `event_kind` is required here, optional on `threshold_breach`

On `threshold_breach` the knob narrows a sum that is meaningful without it. Here "the first event"
has no meaning until the kind is named — a session or an outflow would be judged as the first
deposit. Required is what `REQUIRED_CONFIG_KEYS` means: a key the checker reads with no fallback.

### The suppression TTL is `account_age_hours`, not a new knob

`threshold_breach` suppresses for its own window; the same rule reads correctly here and needs no
product decision the request did not make. The TTL outlives the entity's newness, so an entity
alerts at most once — which is what "first deposit" should mean to a reader of the channel.

### `currency` and `source` on `Event`

The request's message names the currency and the payment method. Both are attributes of the event,
both are optional strings defaulting to `None`, and both are ignored by every existing checker, so
no behaviour moves. `source` is the abstract name: it is where the amount arrived through, the way
`inflow` is what a deposit is here. An attribute the event does not carry reads `unknown` in the
alert text and stays `null` in the context, rather than dropping the field.

This extends ADR-0001's list of abstract event attributes (`entity_id`, `kind`, `amount`, `status`).
It is a deliberate, named extension, not a drift towards live data: no source, no conversion, no
lookup — two descriptive strings that arrive with the event.

## Risks / Trade-offs

- **An entity whose registration event is not in the stream never alerts.** That is the honest
  reading — account age is unknown — and it is a spec'd scenario, not a silent skip.
- **Ties on the creation timestamp.** Two successful events of the same kind at the same instant:
  the first one in the stream wins, stated in the spec so a reader does not have to guess.
- **`registration_event_kind` equal to `event_kind`** would make the registration its own first
  qualifying event and alert about nobody. Legal, surprising, so it is a `config_warnings` message,
  never a rejection — the contract's rule for advice.
