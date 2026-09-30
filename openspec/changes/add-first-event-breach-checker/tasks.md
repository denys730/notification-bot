# Tasks

## 1. The event shape

- [x] 1.1 Add optional `currency` and `payment_method` to `checkers.base.Event`, and verify `uv run pytest tests/` still passes unchanged (every existing construction keeps working because both default to `None`)

## 2. The checker

- [x] 2.1 Add `CheckerCodes.FIRST_EVENT_BREACH = "first_event_breach"` to `src/constants.py` and verify `tests/test_checkers_registry_unit.py` fails on the missing class, which is the guard doing its job
- [x] 2.2 Write `tests/test_checker_first_event_breach_unit.py`, one test per scenario of `specs/checkers/first-event-breach/spec.md` (trigger, age, alert content, suppression, config hooks), and verify they fail for want of the module
- [x] 2.3 Implement `src/checkers/checker_first_event_breach.py` — `CHECKER_CODE`, `REQUIRED_CONFIG_KEYS`, `CONFIG_VALUE_BOUNDS`, `CONFIG_BOUND_REASONS`, `config_warnings`, `check()` — and register it in `src/checkers/__init__.py::ALL_CHECKERS`; verify `uv run pytest tests/test_checker_first_event_breach_unit.py` is green
- [x] 2.4 Add the main spec at `openspec/specs/checkers/first-event-breach/spec.md` and verify `openspec validate --specs` passes and `describe_checker_type("first_event_breach")` reports it as specified

## 3. The reference catalogue

- [x] 3.1 Add the `First Event Breach 1000 24h` row to `src/checkers/catalogue.py::default_rows` and verify `tests/test_checkers_registry_unit.py::test_catalogue_rows_satisfy_their_checker` passes
- [x] 3.2 Add a registration event and a large first inflow for a new entity to `src/checkers/sample_events.py`, keeping that entity out of the session rotation so no existing assertion moves, and verify `tests/test_checkers_registry_unit.py::test_sample_events_drive_every_catalogue_row` shows the new row raising exactly that entity
- [x] 3.3 Teach `tests/test_mcp_checker_types_unit.py` the new code and verify the MCP tool lists five specified types

## 4. Integration

- [x] 4.1 Run `make all-check` and `uv run pytest tests/` and verify both are clean
- [x] 4.2 Run `uv run python src/commands.py run-checker first_event_breach` and verify it prints the alert the new catalogue row raises over the sample events
