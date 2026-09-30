# alert-bot-demo

A demo alerting service. It speaks the **admin API** cadmin's Alert Bot integration expects and
carries an **MCP surface** (read-only tools, guides, checker specs, `propose_alert_changes` → cadmin
review link) — so cadmin, an MCP client and the OpenHands automation connect to it without changes.
Its alert types are abstract, nothing runs on a schedule, nothing is delivered, and the alert
journal is seeded.

| Alert type | What it stands for |
| --- | --- |
| `heartbeat` | the service's own dependencies are reachable (a service alert) |
| `threshold_breach` | an entity's successful amounts over a rolling window reach a threshold |
| `activity_drop` | the brand's event volume falls below its own baseline |
| `status_stuck` | an entity's latest event has sat in a non-final status for too long |

Each has a specification under `openspec/specs/checkers/`, a config catalogue row, and unit tests.

## Run it

```bash
cp .env.example .env            # set ADMIN_API_SECRET_KEY, BRANDS, the cadmin URLs
uv venv -p 3.13 && source .venv/bin/activate && uv sync
docker compose up -d demo-mongo # or point MONGO_URI at any Mongo
uv run uvicorn main:app --app-dir src --reload --host 127.0.0.1 --port 8000   # admin API, seeds demo rows on first start
uv run python src/mcp_server/main.py                                # MCP server on :8811 (HTTP, cadmin OAuth)
```

Or everything at once: `docker compose up --build` (Mongo + API on :8000 + MCP on :8811).

Useful commands:

```bash
uv run python src/commands.py seed --force                    # reset every brand's demo rows
uv run python src/commands.py list-checkers --brand DEMO
uv run python src/commands.py run-checker threshold_breach    # run one checker over the sample events
make test                                                     # unit tests, no infrastructure needed
make all-check                                                # ruff
```

## Connect cadmin

1. In cadmin (superuser → Brands) create a brand whose id is one of `BRANDS`, lower-cased — `demo`.
2. Superuser → Services → add a service of type **Alert Bot**: slug `alert-bot-demo`, brand `demo`,
   base URL `http://<host>:8000`, secret key = `ADMIN_API_SECRET_KEY`. cadmin probes
   `GET /api/healthcheck` on save.
3. Grant users access to that service. The Checkers, Custom segments and Settings pages now read
   this instance.

The service slug (`alert-bot-demo`) is what `propose_alert_changes` needs; read it from
`list_clusters().granted_services` rather than guessing.

## Connect the MCP server

```bash
claude mcp add --transport http alert-bot-demo http://<host>:8811/mcp
```

The first call opens cadmin's OAuth consent; the server then resolves the caller's brands from cadmin
(`/auth/me` + `/services`, type `alert-bot`). `ALERTS_MCP_CADMIN_ISSUER` must equal cadmin's OAuth
issuer (its backend's `OAUTH_ISSUER`) exactly, `ALERTS_MCP_PUBLIC_URL` must be the URL clients reach this server on, and
`ALERTS_MCP_CADMIN_REVIEW_BASE` is the cadmin web host review links point at. A client without a browser
(OpenHands, CI) sends a personal cadmin API token as `Authorization: Bearer`.

Tools: `list_clusters`, `list_alerts`, `get_alert`, `list_checker_types`, `describe_checker_type`,
`describe_alert_contract`, `list_segments`, `validate_segments`, `get_player_current_segments`,
`list_player_segments`, `filter_players_by_segment`, `count_players_by_segment`,
`list_alert_journal`, `get_alert_journal_event`, `list_guides`, `read_guide`,
`propose_alert_changes`.

## OpenHands: new alerts on request

`docs/openhands/` holds the automation behind the `alert_config.requested` webhook, adapted to this
repository: the prompt, the ACP runner, and the scripts that build and deploy the automation file.
The prompt tells the agent to reach a verdict (covered / extend / new), build a cadmin review link for a
covered request, or open a merge request with a spec, a checker, a catalogue row and tests for a
new one. `CLAUDE.md` is the agent's operating manual; `CONTEXT.md` fixes the vocabulary.

## Layout

```
src/main.py                 FastAPI app: /api/healthcheck + the admin routers
src/api/admin/              checkers, global_settings, segmentations, alert_journal, filters, auth
src/checkers/               BaseChecker + the four checkers, the catalogue, sample events
src/storage/mongo.py        alert_bot_system + alert_bot_<brand> databases, no ODM
src/seed.py                 demo rows, settings, segments, journal (idempotent per brand)
src/mcp_server/             the MCP server: app, auth (cadmin), storage, content (guides, specs), tools
openspec/specs/             event-checking contract + one spec per checker
docs/openhands/             the alert_config.requested automation
tests/                      unit tests on an in-memory Mongo
```

## What is deliberately not here

No scheduler, no Slack, no Kafka, no Redis, no real data source, no per-code field schemas (cadmin
renders a JSON editor for these codes). `DELETE /api/admin/checkers/{id}/` really deletes, and the
API seeds rows on startup — both are deliberate; see `docs/adr/0001`.
