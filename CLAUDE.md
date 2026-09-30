# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`alert-bot-demo` is a demo alerting service. It exposes the admin API and the MCP surface cadmin's
Alert Bot integration expects, so cadmin connects to it without changes — but its alert types
are abstract (`heartbeat`, `threshold_breach`, `activity_drop`, `status_stuck`), nothing runs on a
schedule, nothing is delivered anywhere, and the alert journal is seeded. Treat the workflow as
real and the data as fake.

## Ground rules

- **Preserve behaviour.** When refactoring, keep the existing behaviour exactly — same inputs must
  produce the same outputs, the same alerts must be raised for the same events. Config knobs
  (`monitoring_window_hours`, `pending_minutes`, thresholds, TTLs) encode product decisions, not
  implementation details; never drop one because it "looks redundant."
- **When in doubt, ask.** If a change might alter observable behaviour — different result count,
  different alert conditions, different timing — stop and confirm with the user before committing.

## Start of every session

1. **Check whether the OpenSpec CLI is installed:** `command -v openspec`.
   - If it is missing, say so in your first response and tell the user to install it with
     `npm install -g @fission-ai/openspec`. Then continue with the file-based fallbacks below —
     a missing CLI never justifies ignoring the specs.
2. **List what is specified.** With the CLI: `openspec list --specs`. Without it:
   `ls openspec/specs/checkers/`. Do not read the spec files at this point — read them on demand.

## Specs are the reference for existing behaviour

`openspec/specs/` documents how the system behaves TODAY. It is a description, not a wish list.

- Before changing or reasoning about ANY checker, read `openspec/specs/event-checking/spec.md`.
  It holds the contract every checker inherits — per-brand config, validation hooks, brand
  isolation, the VIP/segment/region gates, deduplication, routing, journaling.
- Before touching a specific checker, read its own spec at
  `openspec/specs/checkers/<checker-code-with-dashes>/spec.md`. It states the trigger condition,
  the window, the config knobs, the dedup scope, and the alert content.
- Every checker in this repository is specified. A checker without a spec is a bug: the MCP server
  reports it as unspecified and `tests/test_checkers_registry_unit.py` fails.
- **If the code and the spec disagree, stop and ask.** One of them is wrong.
- When a change alters observable behaviour, the spec moves with it. Use the OpenSpec change
  workflow when the CLI is available (`openspec new change <name>`, delta specs, `openspec archive`);
  otherwise update the main spec in the same commit as the code.

Spec format: `## Purpose`, then `## Requirements` with `### Requirement: <name>` sections, each
followed by `#### Scenario: <name>` blocks written as `- **WHEN** ...` / `- **THEN** ...`.

## Reaching live data

- **cadmin and the back office are reachable ONLY through MCP tools.** No direct HTTP call, no
  database connection, no scraping. If an answer needs data you can only get that way and no MCP
  tool exposes it, say so and stop.
- **Never resolve a group of players one at a time.** `get_player_current_segments` is for ONE
  player. Use `filter_players_by_segment(brand, segments=[...], player_ids=[...])` or
  `count_players_by_segment(...)` for a group.
- **Report a segment by name AND value: `Business Premium (34)`.** Every MCP tool returns it ready
  as `label`.

## Runtime & Tooling

- Python 3.13, async (FastAPI, motor). Dependencies are managed with **uv** (`pyproject.toml` +
  `uv.lock`); do not use pip/poetry locally.
- Configuration comes from `.env` at the repository root (see `.env.example`); `BRANDS` is required
  and the API exits at startup if it is unset.
- `PYTHONPATH=src` in Docker; tests add `src/` to `sys.path` in `tests/conftest.py`. Modules inside
  `src/` import each other as top-level packages (`from checkers import ...`, never `from src.checkers`).

## Common Commands

```bash
uv venv -p 3.13 && source .venv/bin/activate && uv sync      # install
make all-check                                               # ruff check + fix + format (120 cols)
make test                                                    # uv run pytest tests/
uv run uvicorn main:app --app-dir src --reload --host 127.0.0.1 --port 8000   # the admin API
uv run python src/mcp_server/main.py                         # the MCP server
uv run python src/commands.py seed [--force]                 # (re)seed demo rows
uv run python src/commands.py run-checker threshold_breach   # run one checker over the sample events
uv run python src/commands.py list-checkers --brand DEMO
docker compose up --build                                    # mongo + api + mcp
```

Every test is a unit test: `tests/` runs without Mongo (an in-memory Mongo stands in), Redis or Kafka.

## Architecture

Two processes share the code under `src/` and one MongoDB:

1. **Admin API (`src/main.py`)** — FastAPI. `GET /api/healthcheck` plus the admin routers under
   `src/api/admin/`: `checkers.py` (`/api/admin/checkers`), `global_settings.py`
   (`/api/admin/settings`), `segmentations.py` (`/api/admin/segmentations`), `alert_journal.py`
   (`/api/admin/alert-journal`). Auth is one Bearer token (`ADMIN_API_SECRET_KEY`), brand scope is
   the `X-Brand` header, list filters are `?filter=<base64url JSON>` (`filters.py`). On startup it
   seeds demo rows for a brand that has none (`SEED_ON_STARTUP`, `src/seed.py`).
2. **MCP server (`src/mcp_server/`)** — read-only tools over the same Mongo, permissions resolved
   from cadmin (`auth/`), guides under `content/guides/`, specs read from `openspec/specs/`
   (`content/specs.py`), and `propose_alert_changes` (`tools/proposals.py`) — the only route to a
   configuration change: a cadmin review link.

There is NO scheduler and NO delivery. A checker is a pure function: `check(events)` over a list of
`checkers.base.Event` returns the `AlertEvent`s it would raise. `src/commands.py run-checker` runs one
over `checkers/sample_events.py`.

### Storage

`storage/mongo.py`: one shared `alert_bot_system` database holding every brand's `checkers_configs`
rows, plus one `alert_bot_<brand>` database per brand for `global_settings`, `segmentations`,
`player_segments` and `alert_journal`. The MCP server discovers brands from that naming, so it must
not change. No ODM — routers work with plain documents, which is what lets the tests run on an
in-memory Mongo.

### Checkers

- `BaseChecker` (`src/checkers/base.py`) owns the gates (`vip_config_check`,
  `segment_config_check`, `region_config_check`, `audience_check`), deduplication
  (`is_entity_recently_notified` / `mark_entity_as_notified`, keys `{brand}:{CHECKER_CODE}:{entity_id}`)
  and the validation hooks: `REQUIRED_CONFIG_KEYS`, `CONFIG_VALUE_BOUNDS` (inclusive ranges),
  `CONFIG_BOUND_REASONS` (one sentence per bounded knob, say WHY) and the `config_warnings(config)`
  classmethod (advice, never a rejection, must never raise). A bounded knob must also be a required
  one. `checker_threshold_breach.py` is the reference for all four.
- Each checker has a `CHECKER_CODE` (enum in `src/constants.py`) and is registered once in
  `checkers/__init__.py::ALL_CHECKERS`; the admin API validates every config write against the
  registered class.
- Player-targeted checkers run `audience_check` per entity before alerting; brand-level checkers
  (`activity_drop`) apply the gates to the cohort they count.

### Adding a checker (the whole list)

1. `CheckerCodes.<NAME> = "<code>"` in `src/constants.py`.
2. `src/checkers/checker_<code>.py`: a `BaseChecker` subclass with `CHECKER_CODE`, the validation
   hooks, and `check()`; register it in `checkers/__init__.py::ALL_CHECKERS`.
3. A default row in `src/checkers/catalogue.py::default_rows` (the seed reads it; the row must
   satisfy the checker's required keys and bounds).
4. `openspec/specs/checkers/<code-with-dashes>/spec.md` — `list_checker_types` and
   `describe_checker_type` read exactly that path.
5. `tests/test_checker_<code>_unit.py`, one test per WHEN/THEN scenario of the spec, in the
   vocabulary of `CONTEXT.md`. `tests/test_checkers_registry_unit.py` guards steps 1–4.

Nothing seeds the new row into a running brand automatically: an existing brand keeps its rows, and
the new one arrives through the cadmin review link (or `seed --force`, which resets the brand).

## Conventions worth respecting

- Keep `ruff` clean with `lint.select = ["I", "F"]` and 120-char lines.
- Imports inside `src/` are top-level (`from settings import settings`).
- Tests must not rely on ambient env — `conftest.py` sets `BRANDS`, the admin secret and the MCP
  auth variables; every test is `*_unit.py` and runs without infrastructure.
- Money, timestamps and labels in alert text go through the checker's own `alert()` helper with a
  plain f-string; there is no shared formatting layer to keep in step.

## Agent skills

### Issue tracker

Local markdown: issues and specs live as files under `.scratch/<feature-slug>/` in this repo. See
`docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles keep their default names (`needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the repo root plus `docs/adr/`. See `docs/agents/domain.md`.
