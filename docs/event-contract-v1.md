# NetStrike Exercise Event Contract v1

**Schema:** [`schemas/event.v1.json`](../schemas/event.v1.json)

**Stable entry point:** [`schemas/event.json`](../schemas/event.json)

**Implementation:** [`shared/events.py`](../shared/events.py)

**Status:** Version 1.0.0 contract for the blue-team MVP

## Purpose

The event contract is the shared interface between simulation modules, the
scenario engine, safe action adapters, participant and facilitator portals,
Splunk, evaluation, reset validation, and after-action reporting. It does not
encode CITEF-specific hostnames, indexes, ingestion endpoints, or credentials.

An action is not complete merely because code ran. Its event must be valid,
redacted, correlated to an exercise run, safely persisted, and discoverable by
the intended audience.

## Compatibility policy

`schema_version` uses semantic versioning:

- **Major:** incompatible field or meaning changes. Consumers reject unsupported
  major versions before processing the event.
- **Minor:** backward-compatible behavior expressed through existing fields or
  namespaced keys in `extensions`.
- **Patch:** clarifications or validation corrections that do not change the
  meaning of an already-valid event.

The v1 schema is strict at the top level. New v1 data must use `data` or a
namespaced `extensions` key such as `netstrike.evaluator_version`; it must not
invent an unversioned top-level field.

`schemas/event.json` is the stable compatibility entry point and references the
current versioned schema. Code and release artifacts should record the exact
versioned schema they were tested against.

## Required fields

| Field | Purpose |
|---|---|
| `schema_version` | Producer/consumer compatibility |
| `event_id` | Globally unique UUID used for evidence citation and deduplication |
| `timestamp` | RFC 3339 UTC event time ending in `Z` |
| `exercise_id` | Stable exercise definition identifier |
| `run_id` | Unique delivery/run identifier |
| `sequence` | Strictly increasing integer within an exercise/run pair |
| `event_type` | Stable dotted event taxonomy, for example `identity.session.created` |
| `phase` | Exercise phase, not the former numeric attack-module number |
| `source` | Producer kind, component, and optional host |
| `actor` | System, synthetic identity, participant, or facilitator performing the action |
| `action` | Stable machine-readable operation |
| `target` | Affected entity, or `null` when no target exists |
| `outcome` | Status and optional reason |
| `severity` | Evidence/operational severity; not a verdict that activity is malicious |
| `visibility` | `participant`, `facilitator`, `evaluator`, or `internal` |
| `safety` | Simulation, dry-run, allowlist, non-destructive, and control markers |
| `provenance` | Producer/version and optional original event/integrity information |
| `message` | Human-readable description |
| `data` | Redacted event-specific values |

Optional fields connect an event to ATT&CK, learning objectives, checkpoints,
other events, or an external raw-data artifact:

- `attack`
- `objective_ids`
- `checkpoint_id`
- `correlation_ids`
- `raw_data_ref`
- `extensions`

## Phases

| v1 phase | Use |
|---|---|
| `setup` | Provisioning, readiness, fixture, and baseline validation |
| `reconnaissance` | Synthetic OSINT preparation and related evidence |
| `identity` | Helpdesk, SSO, MFA, session, and identity containment |
| `endpoint_ad` | Endpoint access, directory discovery, containment, and remediation |
| `cloud` | Stateful mock-cloud access, exposure, containment, and policy repair |
| `impact_recovery` | Safe marker impact, service/data recovery, and validation |
| `control` | MSEL delivery, checkpoint, hint, safety, health, and error events |
| `post_exercise` | Scoring, hotwash, evidence export, reset, and AAR events |

## Producer requirements

Every producer must:

1. Create events through `EventBuilder` or an equivalent implementation tested
   against `event.v1.json`.
2. Use one `EventContext` per exercise/run and producer.
3. Supply timezone-aware timestamps; the builder normalizes them to UTC `Z`.
4. Assign a monotonically increasing sequence within the run.
5. Use only synthetic identities and allowlisted targets.
6. Populate the safety marker truthfully. The v1 contract cannot represent a
   destructive or non-simulation event.
7. Put reusable secrets and personal data nowhere in an event. The shared layer
   redacts known sensitive keys as a final defense, not as permission to collect
   them.
8. Validate before publishing. Invalid events must surface a producer error and
   must not silently enter the evidence stream.

Example:

```python
from shared.events import EventBuilder, EventContext, EventLedger, entity

context = EventContext(
    exercise_id="silent-spider",
    run_id="run-20260916-001",
    source_kind="controller",
    source_component="scenario-engine",
    producer_version="1.0.0",
    source_host="CTRL01",
)
builder = EventBuilder(context)
ledger = EventLedger("output/scenario_events.jsonl")

event = builder.build(
    event_type="control.inject.delivered",
    phase="control",
    actor=entity("system", "scenario-engine"),
    action="inject.deliver",
    target=entity("msel_item", "MSEL-001"),
    outcome_status="success",
    message="Delivered the initial manager report",
    visibility="facilitator",
    dry_run=False,
    safety_controls=("approved-msel",),
    data={"recipient": "participant-team"},
)
ledger.append(event)
```

## Consumer and ledger requirements

Consumers must reject an unsupported major version rather than guessing at its
meaning. `EventValidator` accepts structurally compatible `1.x.y` events and
rejects any other major.

`EventLedger` adds runtime invariants that JSON Schema alone cannot enforce:

- duplicate `event_id` values are rejected;
- sequence numbers must increase within each `exercise_id`/`run_id` pair;
- separate runs maintain independent sequences;
- timestamps more than five minutes in the future are rejected by default;
- existing JSONL data is revalidated and indexed on process restart; and
- sensitive keys are recursively redacted before the event is written.

Validate a ledger from the repository root with:

```bash
python -m shared.validate_events output/scenario_events.jsonl
```

## Redaction rules

The shared implementation recursively redacts keys including `password`,
`credential`, `secret`, `client_secret`, `token`, `access_token`,
`refresh_token`, `session_token`, `mfa_secret`, `api_key`, `authorization`, and
`cookie`. Matching ignores capitalization, hyphens, and underscores.

Redaction does not make collection of real secrets acceptable. Producers must
avoid collecting them, and adapters should emit identifiers or irreversible
test-only references instead.

## Migration from the issue #49 event shape

`shared.legacy_events.migrate_legacy_event` converts an existing in-memory
event to v1. It is a transition tool, not a permanent ingestion format.

| Legacy field | v1 destination |
|---|---|
| `event_id` | `event_id` when it is a valid UUID; otherwise a new UUID is assigned |
| `timestamp` | UTC `timestamp`; offsets are normalized to `Z` |
| numeric `phase` | Named `phase` using the mapping below |
| `technique_id`, `tactic` | `attack.technique_id`, `attack.tactic` when valid |
| `description` | `message` |
| `source_module` | `source.component` and `provenance.producer` |
| `flag_triggered` | `data.flag_triggered` |
| `raw_data` | `data.raw_data`, after recursive redaction |
| original ID | `provenance.source_event_id` |

Legacy phase mapping:

| Legacy | v1 |
|---:|---|
| 0 or unknown | `control` error |
| 1 | `reconnaissance` |
| 2–4 | `identity` |
| 5 | `endpoint_ad` |
| 6 | `cloud` |
| 7 | `impact_recovery` |

Module migration order after this contract is approved:

1. OSINT profiler and existing ransomware simulator, which already emit the
   issue #49 shape.
2. MFA and mock-cloud services, which currently use console/file logs without
   the shared contract.
3. Identity/helpdesk and endpoint/AD services as their stateful interfaces are
   implemented.
4. Scenario control, participant actions, evaluation, reset, and AAR exports.

During transition, a module may return legacy events to the adapter, but only v1
events may enter the authoritative exercise ledger or Splunk event stream.

## Splunk transport envelope

The contract does not choose an index or ingestion mechanism. When CITEF
supports HTTP Event Collector, wrap the event so Splunk metadata does not
conflict with the contract's structured `source` object:

```json
{
  "time": 1789567200.000,
  "host": "CTRL01",
  "source": "netstrike:scenario-engine",
  "sourcetype": "netstrike:event:v1",
  "event": {
    "schema_version": "1.0.0",
    "event_id": "33333333-3333-4333-8333-333333333333",
    "exercise_id": "silent-spider",
    "run_id": "run-20260916-001"
  }
}
```

For monitored JSONL, use the same `netstrike:event:v1` sourcetype and map the
file/host metadata separately from the JSON payload.

### Normalized Splunk fields

| JSON path | Recommended Splunk field | Type/use |
|---|---|---|
| `schema_version` | `ns_schema_version` | Contract compatibility |
| `event_id` | `ns_event_id` | Evidence citation and duplicate detection |
| `timestamp` | `_time` and `ns_event_time` | Timeline and ingestion-lag checks |
| `exercise_id` | `ns_exercise_id` | Exercise filtering |
| `run_id` | `ns_run_id` | Mandatory run isolation |
| `sequence` | `ns_sequence` | Ordering and missing-event analysis |
| `event_type` | `ns_event_type` | Stable event taxonomy |
| `phase` | `ns_phase` | Exercise phase |
| `source.kind` | `ns_source_kind` | Producer category |
| `source.component` | `ns_source_component` | Producer/service |
| `source.host` | `ns_source_host` | Logical host |
| `actor.type`, `actor.id` | `ns_actor_type`, `ns_actor_id` | Acting identity/system |
| `action` | `ns_action` | Attempted operation |
| `target.type`, `target.id` | `ns_target_type`, `ns_target_id` | Affected entity |
| `outcome.status` | `ns_outcome` | Result filtering |
| `severity` | `ns_severity` | Operational/evidence priority |
| `visibility` | `ns_visibility` | Role-based view filtering |
| `attack.technique_id` | `ns_attack_technique_id` | ATT&CK correlation |
| `objective_ids{}` | `ns_objective_id` | Learning-objective evidence |
| `checkpoint_id` | `ns_checkpoint_id` | Decision-point evidence |
| `safety.*` | `ns_safety_*` | Safety monitoring |

CITEF will confirm the index, ingestion method, retention, and field-extraction
deployment. Those choices must not change the v1 event payload.

### CITEF-neutral SPL examples

Replace `<citef_index>` after the Cyber Range confirms it.

Data health by producer:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$"
| stats count max(_time) as latest by ns_source_component
| eval lag_seconds=now()-latest
| sort - latest
```

Participant-visible timeline:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$" ns_visibility="participant"
| sort 0 ns_sequence
| table _time ns_sequence ns_phase ns_event_type ns_actor_id ns_action ns_target_id ns_outcome ns_event_id
```

Checkpoint/objective evidence:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$"
| search ns_checkpoint_id="DP2" OR ns_objective_id="LO3"
| sort 0 ns_sequence
| table _time ns_event_type ns_action ns_outcome ns_event_id ns_checkpoint_id ns_objective_id
```

Duplicate event IDs:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$"
| stats count by ns_event_id
| where count > 1
```

Safety violations or malformed producer claims:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$"
| where ns_safety_simulation_only!="true" OR ns_safety_destructive!="false" OR ns_safety_within_allowlist!="true"
| table _time ns_source_component ns_event_type ns_target_id ns_event_id
```

Ingestion delay:

```spl
index=<citef_index> sourcetype="netstrike:event:v1" ns_run_id="$run_id$"
| eval ingestion_delay_seconds=_indextime-_time
| stats count avg(ingestion_delay_seconds) as avg_delay max(ingestion_delay_seconds) as max_delay by ns_source_component
```

## Acceptance and change control

Changes to required fields, meanings, phase values, safety constraints, or
ordering rules require a schema review. Breaking changes require a new versioned
schema file and a consumer migration plan; they must never silently replace v1.

The fixtures and tests under `schemas/fixtures/events/` and `shared/tests/` are
the executable acceptance suite for the contract.
