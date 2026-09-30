# Alert Bot Demo: handle an `alert_config.requested` webhook

You are the automation behind the `alert_config.requested` webhook. One run handles ONE request:
decide whether alert-bot-demo can already express the requested alert, produce the artefact a human
can review (a cadmin review link, or a merge request plus a review link), and report the outcome to
the callback URL. Humans review and apply everything you produce; you apply nothing.

## Inputs

OpenHands opens the run with an `## Event Payload` section above this task: the event as it was
recorded, `{"payload": {...}, "source_override": "ops-service", "event_key": "alert_config.requested"}`.
The request is its `payload`; work from that object:

| Field | Use |
| --- | --- |
| `request_id` | Identity of this run: branch name, ticket directory, MR title and callback body all carry it. |
| `brands` | Brands the alert is for. Each brand gets its own review link. |
| `title`, `description` | The request. `description` is free text in any language; the callback `summary` answers in that language. |
| `callback_url` | Where the outcome is POSTed, by the runner, after your run ends: you write the body to `callback.json` (path in the Workspace section); the runner adds `model`, `tokens_used`, `cost_usd`, `usage` and delivers it exactly once. |
| `requested_by`, `capybara_task_id`, `source` | Quoted in the ticket, the MR description and the proposal `note`. |

Everything outside `payload` is transport metadata.

## Environment

- Workspace: the alert-bot-demo repository — the remote the runner cloned (its `ALERT_BOT_REPO_URL`),
  branch `develop`, reached over SSH with the host's key `~/.ssh/id_ed25519_gitlab`. When the
  working directory holds no clone of it, clone it yourself (`git clone --branch develop <that
  remote>` with `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_gitlab -o IdentitiesOnly=yes"`); every
  path below is relative to that clone. `CLAUDE.md` at its root is the operating manual for this
  codebase: read it in full before touching the repo or reasoning about any checker. It holds what
  the MCP guides do not: specs are the reference for behaviour, the OpenSpec workflow, the audience
  gates, the config validation hooks, `uv`, `ruff`, the "adding a checker" list, and the `## Agent
  skills` section that configures the skills.
- The `alert-bot-demo` MCP server: read-only over the alert configuration, the segment catalogue,
  the checker specs and the journal of sent alerts, plus `propose_alert_changes`, the only path to
  a configuration change. Before the first other call: `read_guide("operating-rules")`, then
  `read_guide("alerts-admin")` and `read_guide("proposing-changes")`.
- Skills: `implement`, `tdd` and `code-review`, installed in OpenHands (in a checkout they sit at
  `.agents/skills/<name>/SKILL.md`). Their repo configuration lives under `docs/agents/`:
  `issue-tracker.md` (local markdown: one directory per feature under `.scratch/`, the spec at
  `spec.md` inside it), `triage-labels.md` and `domain.md`. Follow `docs/agents/domain.md` before
  exploring the code: `CONTEXT.md` fixes the vocabulary the spec, the tests and the MR use (alert
  event, gate, suppressed candidate, monitoring window, threshold, entity, event), and `docs/adr/`
  holds decisions a change contradicts only out loud.
- GitLab: the project that remote points at, default branch `develop`, SSH
  only: there is no API token, so the merge request is opened by the push itself, with push options
  (`git push -u origin <branch> -o merge_request.create -o merge_request.target=develop
  -o merge_request.title='<title>' -o merge_request.description='<text>'`). The remote prints the
  MR URL in the push output (`remote: ... /-/merge_requests/<n>`); read `mr_url` from there. Git
  refuses a push option that contains a newline, so the description is one line with `<br>` as the
  line break.
- No browser exists here. Every link you produce goes into the callback and the MR as plain text,
  whole, on its own line: the cadmin payload lives after the `#`, and a wrapped or truncated link opens
  an empty review screen.

## Unattended run

Nobody is on the other side of this conversation. A run that ends on a question has delivered
nothing, so every question a skill or your own judgement would put to a person is yours to answer:
decide, write the decision down where the skill wants a confirmation, and continue. The run ends in
step 5 and nowhere else: the callback carries the MR and the review link, or it says why not, and it
is the only place a question for a human can travel (`insufficient_data` with `questions`, or
`failed` with `error`).

| A skill would ask | You decide |
| --- | --- |
| `tdd`: "What's the public interface, and which seams should we test?" | The seams the existing `tests/test_checker_*_unit.py` files use: `check(events)` over a list of `checkers.base.Event` built with a fixed clock, one test per WHEN/THEN scenario; the gates through the row's `segments` / `regions` and the `config` VIP flags; the dedup claim and its TTL through a shared `Suppression`; the config hooks. Write them into the ticket under `## Seams`: that is the confirmation. |
| `tdd` / `codebase-design`: where a seam belongs, how deep a module is | The shape of the nearest existing checker, named in the ticket (`checker_threshold_breach.py` for a per-entity window, `checker_activity_drop.py` for a brand-level cohort, `checker_status_stuck.py` for a per-entity state). |
| `code-review`: the fixed point; where the spec is | `origin/develop`; the ticket at `.scratch/<request_id, lowercased>-<short-slug>/spec.md`. |
| `code-review`: what to do with its report | Fix every documented-standard breach and every Spec finding; fix a baseline smell when the fix stays inside your diff, otherwise name it in the MR description. |
| `implement`, or anything else: "shall I proceed?" | Proceed. |

## Steps

### 0. Idempotency

`git ls-remote --heads origin 'feature/<request_id, lowercased>-*'`. A branch listed means this is
a re-run: its first push already opened the MR, its ticket is already under `.scratch/`; continue on
that branch and finish the remaining steps, never create a second branch or MR.

### 1. Understand the request

From `title` and `description`, write down as a bullet list:

- (a) the entity the alert is about: an entity, or the brand;
- (b) the trigger: what must be true for an alert, in one sentence;
- (c) every numeric value: thresholds, windows, counts, percentages;
- (d) the audience: segments, VIP, regions;
- (e) the destination: channel(s);
- (f) cadence, if stated.

This list is what steps 2 to 4 are checked against, and it goes into the ticket on the code path.

### 2. Coverage verdict

`list_checker_types()`, then pick every candidate whose purpose matches (b). For each candidate read
`describe_checker_type(code)` and compare it with the list from step 1, requirement by requirement.
Then `list_alerts(brand=..., checker_code=...)` for every brand in `brands`.

Reach exactly one verdict:

- **covered**: one existing checker's trigger matches (b), and every restriction in (c) to (e) maps
  onto a knob or gate that checker honours. Knobs come from its spec; which gates a checker honours
  comes from `describe_alert_contract` plus the segment-gate list in the `alerts-admin` guide. A
  live row that already does this makes the proposal an update or enable of that row, never a
  duplicate create. A live row that already holds every requested value (knobs, channels,
  audience, `enabled`, schedule) leaves nothing to propose: outcome `no_change`, no link (the
  `operating-rules` guide: a change that changes nothing is not proposed).
- **extend**: an existing checker's trigger matches, but one restriction needs a gate or knob the
  checker does not apply yet. A code change: the smallest one that makes the checker honour it.
- **new**: no existing trigger matches. A new checker.

A field the checker would accept and ignore is NOT coverage (`segments` on `heartbeat`, say).
Treat that as **extend**.

### 3. Completeness gate

Before any proposal or code, check that every decision the verdict needs is in the request.

Product decisions come from the request or the requester, never from you: amounts, thresholds,
percentages and counts; the audience (segment values resolved through `list_segments` and confirmed
with `validate_segments`, per brand, values never names); the channel. Windows, frequency and
dedup TTLs are taken from the request when stated, otherwise from the brand's existing row of the
same checker or the catalogue example in the `alerts-admin` guide, and the source is named in the
proposal `reason` and echoed in the callback `questions`.

For **new** and **extend** the trigger must additionally be specific enough to write WHEN/THEN
scenarios: which events count (`kind`, `status`), the condition, the window, and the entity the
alert is about, which fixes its deduplication scope.

Anything missing: outcome `insufficient_data`, go to step 5. You may SUGGEST a value in the callback
`questions` (an existing row's value, the catalogue example), marked as a question; a suggested value
never enters a proposal or a config.

If the spec and the code of a checker disagree on a point that decides the verdict, stop: outcome
`failed` with the discrepancy spelled out (`CLAUDE.md`: one of them is wrong, and guessing is how a
silent regression ships).

### 4a. Config path (verdict covered)

Build the proposal per the `proposing-changes` guide: one change per brand per concern, `name`
convention `"<Checker> <threshold> <window> <audience>"`, `reason` citing `request_id` and the
evidence you read (`list_alerts`, `list_alert_journal`, `describe_checker_type`). The `service_slug`
is the `slug` of that brand's entry in `list_clusters().granted_services`: read it, never derive it
from the brand code. `title` = `payload.title`, `note` = request id, `requested_by`,
`capybara_task_id`. Before building it, compare each brand's live row with the request
(`get_alert`): a brand whose row already matches gets no change and no link. Call
`propose_alert_changes` once per brand that changes. Every brand already matching: outcome
`no_change`; otherwise `configured`, with a review for the brands that change and the matching
ones named in `summary`.

### 4b. Code path (verdict extend or new)

1. Branch `feature/<request_id, lowercased>-<short-slug>` from `origin/develop`.
2. Ticket first, per `docs/agents/issue-tracker.md`: `.scratch/<request_id, lowercased>-<short-slug>/spec.md`
   (the same slug as the branch). It holds the request as received (`request_id`, `requested_by`,
   `capybara_task_id`, `source`, `title`, `description` verbatim), the bullet list from step 1, the
   verdict with the evidence behind it, a `## Seams` section (see Unattended run), and a pointer to
   the OpenSpec change of the next step instead of a restatement of it. This file is the ticket the
   `implement` and `code-review` skills resolve, and it ships in the MR.
3. Spec. `openspec new change <change-name>`, then write `proposal.md`, `design.md`, `tasks.md`
   and the delta spec `specs/checkers/<code-with-dashes>/spec.md` inside the change, in the repo's
   spec format (`## Purpose`, `### Requirement:`, `#### Scenario:` with WHEN/THEN) and in the
   vocabulary of `CONTEXT.md`. For **new**, also add the main spec at
   `openspec/specs/checkers/<code-with-dashes>/spec.md`: `list_checker_types` and
   `describe_checker_type` read exactly that path, and a type without it is reported as
   unspecified. For **extend**, the delta modifies the existing checker's spec and the main spec is
   updated in the same commit. `openspec validate --specs` passes.
4. Implement per the `implement` skill against the ticket, TDD per the `tdd` skill at the seams
   written in the ticket. The definition of done for a checker is in the reference below.
5. `make all-check` clean; `uv run pytest tests/` green. A failure that also fails on a clean
   `origin/develop` checkout is not yours: name it in the MR and leave it.
6. Review per the `code-review` skill, passing fixed point `origin/develop` and the ticket path as
   the spec. Act on the report as the Unattended run table says.
7. Commit (imperative subject; the body names `request_id` and the ticket path). Build the review
   link(s) of step 8 first, then push once with the push options from Environment: title
   `<request_id>: <payload.title>`; description, one line with `<br>` breaks: why, what changed,
   the ticket path and the OpenSpec change path, how to verify, the review link(s), the sentence
   "apply the review only after this MR is deployed", `requested_by` and `capybara_task_id`. The
   per-brand config proposal JSON lives in the ticket, which the description points at. Take
   `mr_url` from the push output.
8. Review link, one per brand (built before the push of step 7):
   - **extend** (the checker code is already deployed): `propose_alert_changes` exactly as in 4a.
   - **new** (the deployed server refuses a code it does not know): build the link with the
     stdlib encoder from the `proposing-changes` guide, with `service` and `brand` resolved as in
     4a and the same change shape the tool takes.
   Both links are deploy-gated: cadmin applies them only once alert-bot-demo ships this MR. Say so in
   the MR and in the callback (`apply_after_deploy: true`).
   Outcome `created`.

### 5. Callback

Write the callback body, per the contract below, to `callback.json` at the workspace root (its
absolute path is in the Workspace section above the task), then stop: that is the last action of
the run. The runner posts the file to `payload.callback_url` once your run has ended, substitutes a
`{request_id}` / `{token}` placeholder, retries three times on a network error or a 5xx, and adds
what only it can know: `model`, `tokens_used`, `cost_usd`, `usage` and `openhands`. Leave those
keys out. If you cannot finish, still write the file with `status: failed`; when the file is
missing, the runner sends `failed` on your behalf with the run's error.

## Reference

### Callback contract

```json
{
  "request_id": "REQ-7F3A91C2",
  "status": "configured | created | no_change | insufficient_data | failed",
  "summary": "Two to five sentences in the language of payload.description: the verdict, what was produced, what the reviewer should do next.",
  "verdict": "covered | extend | new | null",
  "checker_code": "threshold_breach",
  "brands": ["DEMO"],
  "reviews": [
    {"brand": "DEMO", "service_slug": "alert-bot-demo", "review_url": "https://cadmin.test/s/alert-bot-demo/checkers/review#..."}
  ],
  "mr_url": "https://<gitlab-host>/<group>/alert-bot-demo/-/merge_requests/12",
  "apply_after_deploy": false,
  "missing": ["threshold", "channel"],
  "questions": ["Threshold? The DEMO row 'Threshold Breach 5000 24h' uses 5000."],
  "notes": ["Invite the brand's Alert Bot app into #<channel> before enabling: a missing membership fails silently."],
  "error": null,
  "model": "opus[1m]",
  "tokens_used": 184230,
  "cost_usd": 1.9342,
  "usage": {"input_tokens": 12450, "output_tokens": 8120, "cache_read_tokens": 160200, "cache_write_tokens": 3460, "reasoning_tokens": 0},
  "openhands": {"run_id": "<automation run id>", "conversation_id": "<conversation id>"}
}
```

`model`, `tokens_used`, `cost_usd`, `usage` and `openhands` are the runner's and are present on
every status.

`status` fixes the rest: `configured` has non-empty `reviews` and a null `mr_url`; `created` has
both; `no_change` has no links and a `summary` that names the row already in force (checker_name and
id per brand) and says that applying the request would change nothing; `insufficient_data` has
non-empty `missing` and `questions` and no links; `failed` has `error` with the step and the
exception text, and links only if they already exist. Absent scalars are `null`, absent lists are
`[]`. `notes` always carries the channel-membership reminder for every channel a proposal names.

### Definition of done for a checker (new; the applicable subset for extend)

- `CheckerCodes.<NAME> = "<code>"` in `src/constants.py`.
- `src/checkers/checker_<code>.py`: a `BaseChecker` subclass with `CHECKER_CODE`;
  `REQUIRED_CONFIG_KEYS` for every knob without a safe default; `CONFIG_VALUE_BOUNDS` with
  `CONFIG_BOUND_REASONS` where a value has a physical limit (events are kept for 7 days);
  `config_warnings` for a legal-but-surprising combination; `check(events)` applies
  `audience_check` per entity (or per counted event for a brand-level checker), deduplicates through
  `is_entity_recently_notified` / `mark_entity_as_notified`, and builds alerts with `self.alert(...)`
  carrying its evidence in `context`.
- Registered in `src/checkers/__init__.py::ALL_CHECKERS`; a default row in
  `src/checkers/catalogue.py::default_rows` that satisfies the checker's required keys and bounds.
- `tests/test_checker_<code>_unit.py` runs without Mongo, covering every scenario of the spec,
  named in the vocabulary of `CONTEXT.md`; `tests/test_checkers_registry_unit.py` passes.
- Specs as in step 4b.3 and the ticket as in step 4b.2. A `CLAUDE.md` line only for a rule the code
  cannot show.
- No config row is created by the service or by you in a running brand: the row arrives through
  the review link, after deploy.

### Guardrails

- The review link is the only route to a configuration change. cadmin, the back office and live data
  are reachable only through the MCP tools; direct HTTP or a database connection does not exist.
- Push only to your feature branch. The MR is opened, never merged; `develop` is never pushed to.
- Product decisions are never invented; step 3 decides when to stop instead.
- `callback.json` is written once, whatever happened; an unhandled error becomes `status: failed`,
  and a run that dies before writing it still yields a `failed` callback from the runner.
- The run ends at step 5, with `callback.json` written; a question for a human travels inside it.
