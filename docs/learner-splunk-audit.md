# Learner-safe SimCorp audit evidence (#183)

Owner: Aya (implementation), Patrick (live Splunk deployment and acceptance).

Splunk is the main investigation tool. The custom portal remains the exercise
inbox, evidence/submission workflow and safe administration interface, not a
replacement SIEM. This feed supplies observable SimCorp application facts to
support investigation with normal searches, timelines and evidence correlation.
It does not add a new attack or a vulnerable website unrelated to the storyline.

## Separate evidence contracts

| Source | Destination | Content |
|---|---|---|
| Windows Security, PowerShell, Sysmon | `netstrike` | Actual host telemetry, configured by the existing forwarder roles |
| Canonical application ledger | `netstrike_staff`, `netstrike:event:v1` | Complete private audit, including scenario control and assessment |
| Reviewed SimCorp audit projection | `netstrike`, `netstrike:learner:audit:v1` | Explicitly allowlisted simulated application facts only |

Never forward the canonical ledger into the learner index or grant participants
the staff role. `visibility=participant` alone does not authorize projection.
The exact event type, module producer and participant visibility must all match
`dashboard/learner_audit.py`. Unknown types/producers are excluded until reviewed.

The strict output schema is `schemas/learner-audit.v1.json`. Every output row has
original event/exercise/run IDs and timestamp, neutral service/operation, outcome,
`simulated_service=true`, optional entity IDs/types and approved typed facts:

| Service evidence | Examples of approved facts |
|---|---|
| Web submission | Source address and landing ID; no submitted credentials |
| Helpdesk reset | Ticket, caller employee ID and callback-verification flag |
| Identity/MFA | Sign-in, session, factor and challenge IDs; source address/host |
| Endpoint/directory | Connection, process/category IDs, account/group change, object count |
| Mock storage | Principal/key/bucket IDs, policy hash, object-access bytes/counts |
| File availability/recovery | Task, fixture and host IDs, available originals, markers |

No messages/reasons, arbitrary nested data, display names/roles, facilitator
instructions, injects, checkpoints, scores, learning objectives, hints, support
replies, submissions, action receipts, setup manifests or approved baseline policy
hashes are copied. Invalid selected facts fail publication, rather than being
stringified. Source schema errors and known unredacted sensitive keys also block.
This is a projection of trusted synthetic producers, not a general-purpose secret
scanner or a cryptographic authenticity boundary.

These are explicitly **simulated SimCorp service audits**, not fabricated Windows,
vendor EDR or cloud-provider logs. Sysmon is host telemetry, not a complete EDR.
Original synthetic entity identifiers (including existing `sess-red-01` labels)
are retained for joins and safe controls; they are not anonymized. Anna should
review dataset naming for unintended clues before delivery. Do not claim all
training labels are removed or that mock-service actions change real AD/cloud.

## Read-only preview and explicit publication

After publishing the canonical staff spool, run from the reviewed source:

```sh
python -m dashboard.learner_spool \
  --source-spool /var/lib/netstrike/event-spool \
  --output /var/lib/netstrike/learner-event-spool \
  --exercise-id operation-silent-spider
```

Default preview validates both histories and prints counts without writing,
creating output, opening the portal or contacting Splunk. Add `--execute` to
publish at most 10 source batches; `--limit` accepts 1–100 batches. Repeat until
`source_batches_remaining=0`. Private-only batches publish an empty events file
and advance the checkpoint without exposing their records. No external service,
Internet access, licence or new Python dependency is required for projection.

The existing controller timer/service runs canonical export followed by learner
publication, under `netstrike`. Ansible creates both directories. The existing
staff-only collection group gets read access; participants get **Splunk search
access only**, not filesystem access. The Universal Forwarder app monitors the
two separate paths with different index/sourcetype mappings.

## Integrity, bounds and reset

The consumer verifies the canonical hash/checkpoint chain, event schema,
exercise scope, unique event IDs and contiguous per-run sequences. It recomputes
all previously published projections before adding batches. Source/output roots
must be separate, not nested, and must have trusted parents. Private filesystem
permissions, regular files, no symlink/hardlink/device input, a single-writer
lock and bounded reads follow the staff spool contract.

Each call accepts at most 100 retained source batches, 10,000 events and 32 MiB
of source/projected event data; individual canonical limits still apply. This
is a bounded exercise prototype, not an unlimited archive. Exceeding a limit
blocks without deleting history; plan a reviewed archive/new release with
Patrick rather than silently pruning files or resetting checkpoints.

Publication uses private `.pending-*` staging, fsync, atomic batch rename and an
atomic `HEAD.json` checkpoint. Retry adopts only fully verified committed
batches after a checkpoint interruption. Changed source prefixes, retained
output, exercise or projection policy block resumption. There is no destructive
repair or overwrite. Preserve files and investigate failures. Empty stages and
failed private files remain for staff inspection and are never monitored.

Do not edit projection rules in a running release without an explicit migration
plan; changed prior projections are intentionally refused. Versioned policy and
full source fingerprints identify the reviewed implementation. Local checksums
are not administrator-proof signatures, nor exactly-once receiver delivery.

Application reset keeps old evidence and new unique run IDs. VM snapshot restore
must retain evidence externally and coordinate portal/spools/UF checkpoints; a
new path or reset forwarder state can re-index old files. No 20-minute reset
target is imposed. Real snapshot validation remains range work.

## Participant workflow

Open **Investigate - SimCorp audit timeline** in the participant Splunk app. Set
the supplied exercise time range and filter the assigned `exercise_id` and
`run_id` (do not assume the default last four hours fits historical evidence):

```spl
index=netstrike sourcetype="netstrike:learner:audit:v1"
exercise_id="operation-silent-spider" run_id="ASSIGNED-RUN-ID"
| table _time event_id service event_type actor_id target_id outcome facts.*
| sort 0 _time
```

Use the identity, helpdesk and storage starting searches to establish a timeline,
compare recorded verification with SimCorp policy, correlate IDs/hosts and source
addresses with available Windows/Sysmon evidence, and cite event IDs in portal
submissions. Searches summarize activity; they do not identify an event as an
attack or tell participants which response to choose. Host/application streams
need not be one-to-one: mock activity does not necessarily cause a Windows event.

## Patrick's live handoff (still required)

1. Deploy the reviewed bundle, forwarder and Splunk apps offline; confirm both
   publisher commands succeed and all source batches drain without errors.
2. Verify JSON fields, nested `facts.*`, timestamp/UTC parsing, distinct file CRC
   handling, run correlation, freshness, duplicate/loss counts and volume under
   Splunk Enterprise 10.0.1 / 10 GB per day / allocated disk constraints.
3. Use [`dashboard.learner_check`](learner-telemetry-comparison.md) to compare
   independently exported learner Raw Events with the run-scoped local projected
   JSONL, including blocked/success paths and reset. File agreement is not live
   receiver or role acceptance. `dashboard.telemetry_check` remains the separate
   **canonical** contract checker; never filter canonical data into learner input.
4. Search as the actual participant role: learner results appear; staff index,
   canonical sourcetype and private raw/control/assessment content are inaccessible.
5. Test stopped ingestion and snapshot recovery; retain receiver searches,
   role configuration and source/release IDs as acceptance evidence.

Local tests cover all 24 full-play cases plus publication integrity, privacy and
retry. They do not run Splunk, UF, Windows, AD, snapshots or the range network.
`splunk_ingestion_verified` and `external_readiness_verified` remain false.
