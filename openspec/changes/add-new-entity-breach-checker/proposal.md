# Add the `new_entity_breach` checker

## Why

REQ-217BA7F9 (requested by `general-dev-team`, capybara task 8, source `capybara`) asks brand TEST1
for an alert on a first deposit of 1,000 EUR or more made less than 24 hours after registration —
the shape of bonus abuse and stolen cards, which today nobody sees until the withdrawal.

No configured alert type expresses that trigger. `threshold_breach` sums every successful amount
over a rolling window: it has no notion of a FIRST event and no notion of how old the account is,
and `describe_checker_type("threshold_breach")` offers no knob for either. TEST1's live rows confirm
it — `Threshold Breach 5000 24h` and the disabled `Threshold Breach 1000 1h Premium` are both
cumulative sums, and every event in `list_alert_journal(brand="TEST1")` carries a cumulative `total`
(5,200 / 5,700 / 6,100). `activity_drop` is brand-level volume, `status_stuck` is a non-final
status, `heartbeat` is the service's own dependencies. The request needs a new checker.

## What Changes

- A new alert type `new_entity_breach`: an entity's FIRST successful event of a configured kind
  reaches a threshold while the entity's registration is still inside the monitoring window.
- `CheckerCodes.NEW_ENTITY_BREACH`, the checker class, its registration in `ALL_CHECKERS`, and a
  default catalogue row `New Entity Breach 1000 24h`.
- Two optional descriptive attributes on `Event` — `currency` and `source` — so the alert can name
  the currency the amount was reported in and where it arrived through, which the request asks for.
  Both default to `None`; no existing checker reads them and no behaviour changes.
- Sample events gain a registration for one fresh entity and one for an old one, so the new row
  raises exactly one alert over the demo stream and the age gate is visible.

## Impact

- Affected specs: `checkers/new-entity-breach` (new).
- Affected code: `src/constants.py`, `src/checkers/base.py`, `src/checkers/checker_new_entity_breach.py`
  (new), `src/checkers/__init__.py`, `src/checkers/catalogue.py`, `src/checkers/sample_events.py`,
  `tests/test_checker_new_entity_breach_unit.py` (new), `tests/test_checkers_registry_unit.py`.
- Affected tests that only count rows: the catalogue row is seeded, so the row totals in
  `tests/test_admin_checkers_api_unit.py` and `tests/test_mcp_tools_unit.py` and the code list in
  `tests/test_mcp_checker_types_unit.py` all move by one. Arithmetic, not behaviour.
- Affected documentation: `CLAUDE.md` (the alert-type list, and one line in "Adding a checker" for
  the row counts above — a rule the code cannot show), `CONTEXT.md` (the `Event` entry gains the two
  attributes), `docs/adr/0001-demo-without-a-pipeline.md` (an amendment note recording both, rather
  than a silent override).
- No existing checker's behaviour changes: the only edit to shared code is two new `Event` fields
  with defaults.
- Nothing is configured in a running brand by this change. TEST1's row arrives through the cadmin
  review link in the pull request, applied by a human after this change is deployed.
