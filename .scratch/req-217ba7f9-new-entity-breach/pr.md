# REQ-217BA7F9: [Notification Bot] New alert: big first deposit from a fresh account on TEST1

## Why

`general-dev-team` (capybara task 8, source `capybara`) asked for an alert on brand TEST1: a player
makes a first deposit of 1,000 EUR or more within 24 hours of registration — the shape of bonus
abuse and stolen cards, which today nobody sees until the withdrawal.

No configured alert type expresses that trigger. `threshold_breach` sums every successful amount
over a rolling window and `describe_checker_type` offers no knob for a FIRST event or for account
age; `activity_drop` is brand-level volume, `status_stuck` is a non-final status, `heartbeat` is the
service's own dependencies. TEST1's live rows agree — `Threshold Breach 5000 24h` and the disabled
`Threshold Breach 1000 1h Premium` are both rolling sums — and so does the journal: every
`threshold_breach` event it raised carries a cumulative `total` (5,200 / 5,700 / 6,100), never a
first amount on a new account. Verdict: **new checker**.

## What changed

A new alert type `new_entity_breach`: an entity's FIRST successful event of a configured kind
reaches a threshold while the entity's registration is still inside the monitoring window.

- `CheckerCodes.NEW_ENTITY_BREACH`, `src/checkers/checker_new_entity_breach.py`, registration in
  `ALL_CHECKERS`, and the default catalogue row `New Entity Breach 1000 24h`.
- Knobs: `account_age_hours` (required, 1–168), `threshold` (required, ≥ 0), `event_kind`
  (required), `registration_event_kind` (optional, default `registration`), the VIP flags and
  `mentions`. The suppression TTL is `account_age_hours` — no new knob, and it outlives the entity's
  newness, so one account alerts at most once.
- `Event` gains two optional descriptive attributes, `currency` and `source`, so the alert can name
  the currency the amount was reported in and where it arrived through — the message the request
  asked for. Both default to `None`; no existing checker reads them, so no behaviour moves.
- Sample events gain a registration for one fresh entity and one for an old one, so the new row
  raises exactly one alert over the demo stream and the age gate is visible.

### Mapping the request onto this repo's vocabulary

`CONTEXT.md` and ADR-0001 keep the events abstract, so: player → entity, deposit → a successful
`inflow` event, registration → a `registration` event, payment method → `source`. `amount` stays the
single-unit figure the threshold compares against, which is what "EUR equivalent" means here;
`currency` only names how it was reported.

### Documentation that moved with it

- `CLAUDE.md`: `new_entity_breach` added to the alert-type list, plus one line in "Adding a checker"
  — a seeded catalogue row moves the row totals asserted in `test_admin_checkers_api_unit.py` and
  `test_mcp_tools_unit.py` and the code list in `test_mcp_checker_types_unit.py`. Those diffs are
  arithmetic, not behaviour.
- `CONTEXT.md`: the `Event` entry gains the two attributes and the synonym to avoid.
- `docs/adr/0001-demo-without-a-pipeline.md`: an **amendment note**, because this change extends the
  ADR's list of abstract event attributes. The decision stands — the attributes are strings that
  arrive with the event; there is still no data source, no conversion and no lookup. Recorded out
  loud rather than silently overridden, as `docs/agents/domain.md` asks.

## Where the spec and the ticket are

- Ticket: `.scratch/req-217ba7f9-new-entity-breach/spec.md` — the request verbatim, the requirement
  bullets, the verdict with its evidence, the seams, and the TEST1 proposal JSON.
- Spec of record: `openspec/changes/add-new-entity-breach-checker/` (proposal, design, tasks, delta
  spec). The main spec lands in the same commit at
  `openspec/specs/checkers/new-entity-breach/spec.md` — the exact path `list_checker_types` and
  `describe_checker_type` read.
- The OpenSpec CLI is not installed in the run environment (`command -v openspec` is empty), so
  `openspec new change` / `openspec validate --specs` were not run. `CLAUDE.md` prescribes the
  file-based fallback; the change directory follows the format the existing specs use, and
  `tests/test_checkers_registry_unit.py` plus `tests/test_mcp_checker_types_unit.py` assert the spec
  exists, parses and is reported as specified. **Please run `openspec validate --specs` before
  merging.**

## How to verify

```bash
uv venv -p 3.13 && source .venv/bin/activate && uv sync
make all-check                 # ruff check + fix + format, clean
uv run pytest tests/           # 91 passed
BRANDS=DEMO uv run python src/commands.py run-checker new_entity_breach
```

The last command prints one alert for entity `10006` over the sample stream:

> New entity breach on DEMO: entity 10006 registered at … and its first inflow of 1,500.00 EUR via
> card reached 1,000.00 after 1.0h

`make` was unavailable in the run environment, so the `all-check` target's three commands were run
directly (`ruff check .`, `ruff check --fix .`, `ruff format .`). All clean; no test fails on a clean
`origin/main` checkout either.

## Review

Reviewed against `origin/main` on both axes with the ticket as the spec. Fixed: the stale
alert-type list in `CLAUDE.md`; a missing `CONFIG_BOUND_REASONS` entry for `threshold`; `proposal.md`
and `tasks.md` not declaring the documentation and row-count edits; a `registration_event_kind: null`
row that ran as same-kind but returned no warning (the fallback is now one classmethod both paths
call); a duplicated earliest-per-entity loop (now one `_earliest_per_entity(events, keep)`); two
unclear names; and three missing tests — the >168 rejection, the tie-break rule, and the
registration's status being ignored.

Left deliberately, named here as the review asks: `amount` + `currency` are two primitives rather
than one Money type. The flat `Event` dataclass and ADR-0001 argue for keeping it that way; raising
it would be a separate change to every checker.

## The configuration change for TEST1

The row is **not** created by this pull request. It arrives through a cadmin review link, which a
human applies field by field:

https://cadmin.nextvp.club/s/notification-bot-test1/checkers/review#AY1UwW7bRhD9lcH2IBugXEmxbIdBDzHgoD00SGP10iAglssRudVyV91dShGM_HvfrsQ4sYMgugicGQ7fezPzHsROlPNCBPY7rViUwrqo11rJqJ2d1i5OI4c4F4WovbQNClZ396v0LIfYOY-ANOxjLm24d9NebZFVnmXkppIRFYvZ4mo6ezl9MVvNL8vLq_LFzT-pppO25SDKDw_CbVE3bIEjpoxrMhbeV2yjjoeqRj_VIWVln1JveU93OUW3OUXz2WxGi8tUg0BwFlXv7_6aLubXt6-v37yks5Yte2kAcwdWsi9Iye2hll5SlGFDN-clZXbUyUDWkR8M09p5kmSkb5ne_PH-fkWyd4ONtPauR2btOXQklUrBCzI6xCpLEs6yZL_llucUOrcPFDsmZVyAqOQRKGiy6lIHZ5qRyfLEZEJ4Pb_R6CBrw813ijPteUfvPPd66CcFSc-EaXTob4y2Ld3__ef9K2o4KK9rrlTHasO-ioctn03i2PAk8eR8ZL-xrs7sE4K19kDMO4yDEMqiHCmTbLnISB-pV_-6wVtpvlVAOYs2fUht_IGefvnUXUMYqQPI7oFDkhr6wWAdd0zRRWnobFkswPlXWhbX-f-qgAjnBdnUN00kYz1NyVlEsEiPE_qdreJMKoWf7Rid9LmgR63nRVJ5nAZGM3abgjzttW3cPuue0p7_GzBe9pPwKm0Hnqw6VL22A26J5kvS2AO5YXtcofRO1mkCZT5BwzSzH22FTx8DFrRZG9m2kKqWakNZrvxt3O6FSFeN63sQ48B_5nSOW7JNHVD62tJRG0A7qhoGpTiE9WBI27UBktwi8coa7XXstEUz6rACgdwaAw0oakHMyxEZ27zPoox-4EI8UwmmtCxELz9V2oYoMbCQfSpZhmWTPEP8ku3meGriYzINrFebCJ-GU2E4VYYhysVlIb4sHFoBK1Ckhas2OvvakU52j0es1TclX2eyf0HXaqe31QDfCiOZY9ji5WepPqnpLJ4fPuMH0BDXpKF8ePuV79Ktix8pzSmzK6nW7Un_hrcu6O-bT9r10Z1h4_zUAKdfVhMnd6Cndoj86IdV8sNKN3SDYICCOJgxJz7_Dw

That link is **deploy-gated**: the deployed server refuses a checker code it does not know, which is
why it was built with the stdlib encoder from the `proposing-changes` guide rather than by
`propose_alert_changes`. **Apply the review only after this PR is merged and deployed.**

It proposes one row on TEST1: `New Entity Breach 1000 24h`, `#demo-alerts`, enabled,
`frequency_minutes: 15`, config `{account_age_hours: 24, threshold: 1000, event_kind: "inflow",
registration_event_kind: "registration", check_vip_users: true, check_non_vip_users: true,
mentions: {}}`. The full JSON is in the ticket.

Two notes for the reviewer:

- `frequency_minutes: 15` is **not** from the request, which is silent on cadence. It is taken from
  TEST1's existing `Threshold Breach 5000 24h` row. Change it if 15 minutes is wrong.
- Before enabling, the brand's Notification Bot Slack app must be a member of `#demo-alerts` — a
  missing membership fails silently.

---

Requested by: `general-dev-team` · capybara task: `8` · request: `REQ-217BA7F9` · source: `capybara`
