---
title: Operating rules
description: How to work with alert-bot-demo through this server — segment reporting, group queries, config editing, channels, and what this server will not do. Read this first.
---

# Working with alert-bot-demo through this server

## What you are looking at

A demo alerting service. Its alert types are abstract (`heartbeat`, `threshold_breach`,
`activity_drop`, `status_stuck`), nothing runs on a schedule, and the alert journal is seeded.
Everything else is the production workflow: the configuration rows, the cadmin admin
pages, the review links, and the specifications behind each alert type.

Alerts are rows of `checkers_configs`, one per rule, unique by `(brand, checker_name)`. One brand
can carry several rules with the same `checker_code` — different thresholds, windows, audiences,
channels. So "the threshold alert" is rarely one row: always `list_alerts(brand=...)` before
concluding anything about what a brand has.

`config` is replaced whole on update through cadmin. Read the current one with `get_alert` and propose
only the keys that change — the review link merges `config` per key, so a partial `set.config` is
the right shape there.

Thresholds, windows, frequencies and TTLs are product decisions. Take them from the ticket or the
requester; never invent one. If the request is silent, propose a value and mark it as a question.

## Report a segment by name AND value

Write `Business Premium (34)`. Never `Business 34`, never `Premium` alone. Every segment-returning
tool hands you this ready in `label` — quote it verbatim. The value is what the configuration and
every query key on; the name is what the reader recognises.

## Never resolve a group of players one at a time

`get_player_current_segments` is for ONE player. Looping it over a list costs one round trip per
player and discards almost everything it returns. When the segmentation and value are already known
— every "who got this alert, and are they Premium" question — ask once:

| Question | Tool |
| --- | --- |
| Which of THESE players are currently Premium? | `filter_players_by_segment(brand, segments=["Business__34"], player_ids=[...])` |
| Which players of the brand are Premium? | `filter_players_by_segment(brand, segments=["Business__34"])` |
| How does this group split across Business? | `count_players_by_segment(brand, segmentation_id="Business", player_ids=[...])` |

Statistics on the players alerted from a segment is two calls, not N+1: `list_alert_journal(...)`
for the events (each with its `player_id`), then one `count_players_by_segment(...)` over those ids.

## `segments` entries take the value, not the name

An alert's `segments` field is a list of `{segmentation_id}__{segment_value}` strings. `Premium` is
a display name; `Business__34` is the entry. Resolve with `list_segments(brand, query="premium")`
and use the returned `config_entry` verbatim, then `validate_segments` before proposing — a value
that does not exist narrows the audience to nobody, silently.

Only `threshold_breach` and `status_stuck` honour the segment gate per entity; `activity_drop`
applies it to the cohort it counts; `heartbeat` ignores it. Setting it where it is ignored reads as
a restriction that is not applied.

## Channels

Get the exact channel from the requester; never guess. In production the brand's Slack app
must be a member of the target channel and a missing membership fails silently; the demo delivers
nothing, but the reminder stays in every proposal so the habit survives the demo.

## This server reads; it does not write

There is no tool here that creates, edits or deletes anything — deliberately. Changes go through a
cadmin review link built by `propose_alert_changes`, which records who approved what. When a request
needs a write, build the proposal; do not look for a way around it.

## A change that changes nothing is not proposed

Before proposing, read the live row with `get_alert` and compare it with the request: every
`config` knob, the channels, the audience (`segments`, `regions`, the VIP flags), `enabled`,
`frequency_minutes` or `cron`. When the row already holds every requested value, say so — "this is
already configured this way; applying it would change nothing" — and build no link. A matching row
that is disabled is not in force — the change is `enabled: true`, and that is what gets proposed.

## cadmin and the back office

Reachable only through MCP tools. No direct HTTP, no database connection, no scraping. If an
answer needs data no tool exposes, say so and stop.

## What you can see

Scoped to the person whose session you are acting under. cadmin grants access per (brand, service);
`list_clusters` shows exactly what is granted, and naming an unavailable brand fails with the list
of what is.
