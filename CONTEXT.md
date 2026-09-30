# Alert Bot Demo

A multi-brand alerting system built for demonstrations: checkers examine one brand's event stream
and raise the situations an operations team needs to see. The vocabulary is production-grade, the
data is not.

## Language

### Alerting

**Alert Event**:
One decision by a checker that something needs announcing. It is the unit of alerting, and it is
counted once no matter how many places it was announced in.
_Avoid_: alert (ambiguous — could mean the event or one message), notification

**Delivery**:
One alert event pushed to one destination. An event fanned out to two channels has two deliveries,
which may succeed and fail independently.
_Avoid_: send, message

**Service Alert**:
An operational message about the alerting system itself, sent to a brand's monitoring channel. Not
a business alert: it announces that a dependency failed, not that a situation occurred.
_Avoid_: error alert, internal alert

**Suppressed Candidate**:
A situation a checker found and deliberately did not announce — rejected by deduplication or by an
audience gate. It never becomes an alert event.
_Avoid_: skipped alert, blocked alert, muted alert

**Run**:
One execution of one checker row for one brand. In this demo a run is `check(events)` called once.
_Avoid_: execution, tick, job, cycle

**Correlation**:
The grouping of alert events that concern one ongoing situation across runs — the same entity, the
same brand-level outage. Derived from the entity the checker deduplicates on.
_Avoid_: incident id, group id, thread

**Entity**:
What an alert event is about, in the terms of the checker that raised it: an account-like subject
identified by `entity_id`, or the brand itself for a brand-level checker.
_Avoid_: subject, target, player (the cadmin pages say player; the checkers say entity)

**Checker**:
A rule that examines one brand's events and raises alert events. Configured per brand and per row,
so one checker can back several rows over the same brand with different thresholds.
_Avoid_: monitor, rule, job, detector

**Event**:
One thing that happened to one entity: a kind, an amount, a status, a creation time, and optionally
the currency the amount was reported in and the source it arrived through. The only input a checker
reads. An amount is always a single-unit figure; the currency only names how it was reported.
_Avoid_: transaction, order, record, payment method (the request says payment method; the events say
source)

### Audience

**Gate**:
A per-checker restriction on what an alert may concern — VIP status, segment, region. A gate
rejects candidates; it never changes an alert already raised.
_Avoid_: filter, guard, check

**Segment**:
One value of a segmentation an entity currently belongs to, written `{segmentation_id}__{value}`
in configuration and reported as `Business Premium (34)` — name AND value — everywhere else.
_Avoid_: tier, group, label (the display name alone)

**Monitoring Window**:
The rolling period ending at the run's clock over which a checker aggregates events. Also the
suppression TTL of the checkers that alert per window.
_Avoid_: period, lookback, range

**Threshold**:
The value an aggregate must reach for a checker to raise an alert event. Operator-owned data in the
row's `config`, never a code constant.
_Avoid_: limit, cap, trigger value

### Configuration

**Row**:
One `checkers_configs` document: one rule of one checker on one brand, unique by
`(brand, checker_name)`.
_Avoid_: config (ambiguous with the `config` object inside it), checker (the class)

**Knob**:
One key of a row's `config` object. Required when the checker reads it with no fallback.
_Avoid_: parameter, setting (a global setting is a different thing), option

**Global Setting**:
One per-brand `{name, value}` document outside any row — the regions catalogue, the default region.
_Avoid_: brand config, brand option

**Proposal**:
A set of changes to a brand's rows packed into a cadmin review link, applied only by a human who ticks
each row. The only route to a configuration change from an agent.
_Avoid_: patch, edit, update request
