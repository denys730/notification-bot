# Tasks — `new_entity_breach`

## 1. Spec

- [x] 1.1 Delta spec at `specs/checkers/new-entity-breach/spec.md`
- [x] 1.2 Main spec at `openspec/specs/checkers/new-entity-breach/spec.md` — the exact path
      `list_checker_types` and `describe_checker_type` read

## 2. Tests first

- [x] 2.1 `tests/test_checker_new_entity_breach_unit.py`, one test per WHEN/THEN scenario
- [x] 2.2 Extend `tests/test_checkers_registry_unit.py` with the new catalogue row's expected alert

## 3. Implementation

- [x] 3.1 `CheckerCodes.NEW_ENTITY_BREACH` in `src/constants.py`
- [x] 3.2 `Event.currency` and `Event.source` in `src/checkers/base.py`, both optional
- [x] 3.3 `src/checkers/checker_new_entity_breach.py` with the validation hooks and `check()`
- [x] 3.4 Register it in `src/checkers/__init__.py::ALL_CHECKERS`
- [x] 3.5 Default row `New Entity Breach 1000 24h` in `src/checkers/catalogue.py::default_rows`
- [x] 3.6 A registration and a first inflow in `src/checkers/sample_events.py` so the row fires

## 4. Documentation the code cannot show

- [x] 4.1 `CLAUDE.md`: the new code in the alert-type list, and the row-count note in "Adding a checker"
- [x] 4.2 `CONTEXT.md`: `Event` gains `currency` and `source`, with the synonym to avoid
- [x] 4.3 `docs/adr/0001-demo-without-a-pipeline.md`: an amendment note for both

## 5. Verify

- [x] 5.1 `make all-check` clean
- [x] 5.2 `uv run pytest tests/` green
- [x] 5.3 Review against `origin/main` with the ticket as the spec, and act on both axes
