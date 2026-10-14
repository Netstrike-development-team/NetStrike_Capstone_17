# Compare application evidence with a saved Splunk raw export

**Ownership:** Aya supplies this application-side check (#157). Patrick selects,
configures and tests actual ingestion/access/retention under #102 and deployed
rehearsals under #104. No Ansible/Splunk settings or live services are changed.

Patrick's October 7 #101 evidence demonstrates offline dashboard installation
and Windows Sysmon transport. It does **not** show that the canonical application
ledger reached Splunk intact. This offline tool makes that next comparison
repeatable without adding a client library, credentials or Internet dependency.
It is included in the existing bundled `dashboard` source tree and uses the
already-required shared JSON Schema validator.

## Obtain two independent staff-only files

1. Choose one exercise/run and an exact source revision. Stop play and finish
   the planned audit/export operations, or explicitly record a fixed prefix
   boundary. Save its canonical staff JSONL export, beginning at sequence 1, as
   `expected.jsonl`. Keep it independent of the receiver export; do not recreate
   the baseline from Splunk or use the same file for both inputs. A frozen
   archive excludes its own archive-created and later reset audits. A live ledger
   can grow after export; stop/export timing must be recorded. Neither is silently
   treated as the complete final ledger.
2. Patrick finishes the selected transport, waits for its backlog to drain, and
   runs a **staff-authorized**, run-scoped search over canonical application events
   only. Use the approved index/sourcetype and a time range covering the baseline.
   Do not use `head`, `dedup`, `stats`, transformed `_raw`, or other filtering that
   conceals faults. Windows Sysmon XML is not canonical application JSON and must
   be tested separately. Record the search, role, absolute time window, job/run
   identifiers, source revision and transport/checkpoint state separately.
3. In Splunk Web, export **Raw Events** and save all results as
   `observed.jsonl`. The contract is one original canonical JSON object per line;
   CSV and JSON search-result envelopes are deliberately unsupported. Splunk 10.0
   documents Raw Events export for event searches, optional result-count limits,
   and possible search reruns when results are not fully retained. Select the
   complete results, not a limited preview, and retain the actual export/search
   receipt. See [official export instructions](https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.0/export-search-results/export-data-using-splunk-web).

Do not put either raw file in Git, public attachments, learner downloads or a
participant-readable directory/index. They can include facilitator answers,
evaluation/submissions and private support data. Visibility labels are not RBAC.
Use approved staff storage outside VMs that will be reverted, and record hashes
at transfer. Files should be regular, unlinked files in trusted staging locations;
the CLI rejects symlink leaves, hardlinks, devices, FIFOs and changed inputs.
It does not enforce staff ACLs or detect an untrusted parent-path substitution.

## Run offline

From the matching source directory with its installed Python environment:

```sh
python -m dashboard.telemetry_check \
  --expected /approved/staff/expected.jsonl \
  --observed /approved/staff/observed.jsonl \
  --exercise-id operation-silent-spider \
  --run-id THE-RECORDED-RUN-ID
```

The tool reads only the two supplied files and shared schema. It does not open
SQLite, construct a portal, publish events, write a report, start a server,
connect to Splunk or invoke an installer. Save stdout/stderr and its exit status
through the approved evidence process; this tool does not create storage for you.

- Exit **0**: supplied files agree, regardless of receiver order or JSON whitespace
  and key ordering. The full canonical payload is compared, including nested
  evidence, timestamp, sequence, source, safety and visibility.
- Exit **1**: usable inputs disagree. Counts identify missing event IDs, changed
  expected IDs, repeated receiver IDs, and unexpected receiver rows. Categories
  can overlap: a changed duplicate counts as both, and unexpected duplicates
  contribute repeated unexpected rows. Missing-source counts help identify gaps.
- Exit **2**: unsafe/invalid input. Empty baseline, mixed run/exercise, schema
  errors, duplicate JSON keys, non-finite values, known unredacted secret fields,
  non-contiguous/duplicate baseline events, malformed/truncated JSON and input limits
  are refused. An empty observed file is a mismatch, never a vacuous success.

Each input is limited to **32 MiB / 10,000 events**, with **256 KiB per line**.
These are small-exercise limits, not a general bulk SIEM export parser. Preserve
oversized evidence and ask Aya to reassess the limit; do not remove rows merely
to make the check pass. The baseline must be an ordered contiguous prefix from
sequence 1; selected visibility-only or mid-run batch files are not accepted.

Output contains fixed status, counts and hashes—not event bodies, identifiers,
source labels or paths. Known key redaction is not a free-text secret detector.
Review source evidence before transferring it. Checksums are not signatures.

## What a match proves—and does not prove

A match proves semantic agreement of **these supplied files only**. It cannot
establish that the observed file came from Splunk, that the baseline is the full
final ledger, or that a manually selected search represents every ingested event.
Independent search/export provenance is Patrick's responsibility. Do not label a
local copy/self-comparison as receiver testing.

`live_splunk_verified` and `external_readiness_verified` remain **false** even
on exit 0. This check does not inspect extracted-field searchability, Splunk
`_time`, latency/freshness, RBAC/participant denial, retention, license/disk volume,
exactly-once transport, services, snapshots or learner admission. Record those
separate #102–#104 checks and their evidence; this CLI cannot close those issues.

If events are missing, inspect scope/time window, exporter backlog, forwarding
and truncation. For duplicates, inspect replay and forwarder checkpoints. For
changed events, inspect wrapping/line breaking/truncation and preserve both
original files. Never edit the source/spool/exports to conceal a failing result.

Related: [canonical spool](event-spool.md), [event contract](event-contract-v1.md),
[source/revision check](offline-release-source-check.md), and
[milestone gates](milestone-release-checklist.md).
