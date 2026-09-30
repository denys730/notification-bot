# ADR-0001: A demo without a pipeline

Status: accepted · 2026-09-30

## Context

The demo exists to show cadmin, the MCP server, cadmin review links and agent-driven alert creation
to a business audience. What they need to see is the workflow:
configuration rows in cadmin, an assistant reading them through MCP, a review link that a human
applies, and a new alert type arriving as a merge request with a spec and tests.

## Decision

The demo keeps the SURFACES — the admin API contract, the MCP tools and guides, the OpenSpec
layout, `CLAUDE.md`, the OpenHands prompt — and drops everything a production alerting service
has behind them:

- no scheduler: a checker is `check(events)` over a list, run by hand or by a test;
- no delivery: an `AlertEvent` is returned, never sent; the journal is seeded;
- no live data: events are abstract (`entity_id`, `kind`, `amount`, `status`), the sample stream
  is generated;
- abstract alert types: `heartbeat`, `threshold_breach`, `activity_drop`, `status_stuck`, chosen
  to exercise every shared mechanism (service alert, per-entity window with gates, brand-level
  cohort, per-entity stuck status) without naming a real product.

Two choices are deliberate: the demo SEEDS rows for a brand that has none, and
`DELETE /api/admin/checkers/{id}/` really deletes, so a review link's `delete` change is visible.

## Consequences

- cadmin connects with no changes; anything cadmin renders comes from the same endpoints.
- A new checker is spec + class + catalogue row + test — small enough for an unattended agent run,
  large enough to demonstrate the review loop.
- Nothing in this repository should grow towards real data sources. The moment it needs one, it
  has stopped being a demo.
