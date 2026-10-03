# Canonical application-event spool

**Owner:** Aya (export implementation); Patrick (UF/Splunk deployment and acceptance).
**Tracking:** #129, #102, #35. Follows #123; integrates with proposed #127/#128.

The application currently writes normalized events to SQLite, whereas Patrick's
proposed Universal Forwarder roles collect Windows Security/PowerShell/Sysmon and
Linux system logs. This exporter supplies the missing **local monitored-file
source**. It does not install/configure a forwarder, run a background service,
contact Splunk, require HEC credentials, or change the portal's event sink.
No new Python dependency, licence or Internet connection is needed.

## Staff-only boundary

The output is the complete canonical ledger for one exercise across its runs,
including `participant`, `facilitator` and `evaluator` visibility. **All files
and any receiving Splunk index must be staff-only.** A visibility field is not
access control. These raw events can contain branch answers, checkpoint results,
human review history and submissions. Never put them in a participant-searchable
index, share the spool through the portal, or expose its directory over HTTP.

Known sensitive keys must already be redacted; invalid/unredacted input is
refused, not silently rewritten. Arbitrary prose cannot be sanitized by key
redaction. Continue using synthetic identities and reviewing free-text sharing.
The existing participant portal remains the safe, filtered learner interface.
A separate participant-safe Splunk feed is not implemented by this milestone.

## Preview and publish

Run from the reviewed application source directory using its Python environment.
Patrick's proposed service uses `/opt/netstrike/current` as its working directory
and `/var/lib/netstrike/portal.sqlite3` as its database. Example paths below are
handoff conventions, not a deployment already performed or a range allocation.

```sh
cd /opt/netstrike/current
/opt/netstrike/venv/bin/python -m dashboard.event_spool \
  --database /var/lib/netstrike/portal.sqlite3 \
  --output /var/lib/netstrike/event-spool \
  --exercise-id operation-silent-spider
```

Default mode is a read-only, advisory preview. It validates source/spool integrity
and prints counts/bytes, without making the destination, lock or checkpoint.
It does not construct a portal, start a run, emit an event or migrate the database.
It opens the existing SQLite file with `mode=ro`, enables `query_only` and uses
a consistent read transaction. SQLite's own WAL/shared-memory bookkeeping is
not a guarantee that operating-system file metadata never changes.

Add `--execute` to publish **one** new batch. Repeat or schedule the same command
until `events_remaining` is zero. `--limit` is 1–1000 events (default 500).
Each event is at most 256 KiB and a batch is at most 20 MiB; a byte boundary can
select fewer events than requested. No daemon, scheduler or automatic admission
gate is introduced. Preview counts can change before execution; execution
revalidates under an exclusive local publisher lock.

The parent directory must already exist. Use a dedicated real spool directory,
not the database directory, repository root or a directory containing other
data. The source database must already exist; it cannot live inside the spool.
The destination and spool-owned descendants reject symlinks, hardlinked files,
devices, unexpected contents, world access and group-writable files/directories.
The caller-selected parent is resolved normally, allowing macOS `/tmp` aliases;
the parent must be a trusted staff-managed location, not participant-writable.

New directories are `0700` and files `0600`. Patrick can grant the dedicated UF
service identity read-only access using an approved staff-only group (`0750`
directories, `0640` files are accepted) or run collection under the approved
identity. Do not grant group write, world access, participant accounts or portal
HTTP access. Linux/POSIX locking/atomic rename/fsync are required; Windows output,
network filesystems and concurrent portal-process orchestration are not supported
or certified. Normal portal writes can continue; the read transaction closes
before file publication to avoid holding its read lock during filesystem writes.

The module is in `dashboard/`, so Patrick's proposed source-tree bundle in #128
includes it without a separate `scripts/` transfer or packaging change. Select
a reviewed revision containing it when assembling the offline release.

## Publication, checkpoint and restart

```text
event-spool/
  HEAD.json
  .lock
  batch-00000000000000000001-00000000000000000500/
    events.jsonl
    manifest.json
  .pending-<opaque-id>/       # interrupted private stage, never monitored
  .head-<opaque-id>           # interrupted checkpoint replacement, never monitored
```

`events.jsonl` is newline-terminated UTF-8: one original v1 event per line, not
a HEC envelope or CSV. Original event IDs, exercise/run correlation, timestamps,
run sequence, nested source/evidence/outcome/safety and visibility are preserved.
Files are immutable from the exporter; they are never appended, rotated or
rewritten. Application reset does not remove or republish earlier batches.

Each batch manifest has counts/bytes/checksum, first/last database cursor, and
previous/next cumulative checkpoints. `HEAD.json` is the durable latest marker.
The cursor is SQLite insertion rowid, **not** the per-run event sequence; run
sequence restarts after application reset. Other exercises can create gaps in
cursor numbers. The database index fields must match the validated payload, and
each selected run's events must have contiguous sequences starting at one.

The exporter verifies all published batch files/checkpoints and streams the
corresponding source prefix before selecting new rows. It compares file content
against the source even if a file checksum was recomputed. Prior deletion,
mutation, incompatible schema, source rollback or reordered rowids (including a
database rebuild/VACUUM that changes rowids) block resumption. This deliberate
MVP integrity check is O(total previously exported evidence), with bounded event
bodies/one-batch buffers; it is not an enterprise-scale stream processor.

Publication writes and fsyncs a private stage, atomically renames its complete
directory to the deterministic `batch-...` name, syncs the directory, then
atomically updates/syncs HEAD. A crash before rename leaves no visible committed
batch. A crash after rename but before HEAD update can adopt the already-verified
batch on retry without publishing it twice. A failed first HEAD write is
recoverable only when no batch has been published. Concurrent writers are refused.
Incomplete stages remain preserved for staff inspection; no automatic cleanup
deletes evidence. Filesystem/hardware durability still depends on the approved
local storage and should be tested in the range.

**Do not delete committed batches, reset HEAD or edit manifests to force
progress.** Preserve the source/spool, diagnose locally and escalate to the
environment owner. Moving to a new/empty spool, deleting the entire spool or
restoring both source and checkpoint can replay older events. Rowids/checksums
are local correlation aids, not signed authenticity or administrator-proof
integrity. There is no pruning, archival retention service or backfill repair.

## Splunk handoff and acceptance (Patrick)

This is a monitored-file contract, not deployable Splunk/Ansible configuration.
Patrick owns the following deployment decisions and live verification:

- Schedule the exporter under the approved unprivileged staff account with the
  same source revision/schema and private output location. Record failures and
  backlog/byte counts without logging event bodies or secrets.
- Monitor **only** paths matching `/batch-[0-9]{20}-[0-9]{20}/events.jsonl$`.
  Do not ingest HEAD/manifests, `.pending-*`/`.head-*`, the SQLite database, or
  unrelated exports. Disable symlink following. Use `monitor`, not the destructive
  Splunk `batch` input, so the exporter can continue verifying retained files.
- Choose a distinct raw-JSON sourcetype and a staff-only index/role policy. Parse
  one JSON object per line; keep nested fields, original `timestamp` as event time
  and `event_id`/`exercise_id`/`run_id`/`sequence`/`source.component` searchable.
  Configure adequate event truncation/line-breaking for up to 256 KiB lines.
- Immutable batches can share the beginning of their JSON content. Review file
  identity/CRC handling so distinct paths are not mistaken for the same file;
  changing a monitored path or resetting forwarder checkpoints can re-index it.
- Verify source-by-source event IDs/counts, backlog drainage, field/time parsing,
  visibility, access denial for participants, duplicates, ingestion delay and
  license/disk volume in Splunk Enterprise 10.0.1. Include application events in
  the run-correlated readiness probes; local export success cannot pass that gate.
- Export/retain evidence outside reverted VMs before snapshot restoration. Preserve
  new unique run IDs and test restored source/spool/UF checkpoint behavior together.

`splunk_ingestion_verified` is always false. Local publication has no receiver
acknowledgement, exactly-once delivery guarantee, readiness sign-off or license
measurement. Missing UF access/configuration/receiver availability must be detected
in Patrick's environment. After Splunk search confirmation, he can record actual
acceptance evidence in #102/#104/#86; this exporter does not close those issues.

Relevant official Splunk 10.0 references:
[inputs.conf](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.0/configuration-file-reference/10.0.0-configuration-file-reference/inputs.conf)
documents monitoring, filtering, CRC identity and destructive batch inputs;
[props.conf](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.0/configuration-file-reference/10.0.0-configuration-file-reference/props.conf)
documents event boundaries, truncation, timestamp recognition and JSON extraction.

## Contained runnable developer demonstration

```sh
python -m dashboard.event_spool_demo
python -m dashboard.event_spool_demo --execute --output /tmp/netstrike-spool-demo-UNIQUE
```

The first command is inert. Explicit execution requires a new directory and uses
the real identity-slice service: start partial play, publish opening events,
stop/archive/reset, start/stop fresh partial play, publish new evidence, and
repeat publication with zero new events. It writes a synthetic SQLite database,
two private batch directories and a count-only `demo-summary.json`. No UI server
or Splunk/network connection remains running. Both runs are deliberately partial;
the saved AAR stays stopped/provisional. This is not a complete 2h50 exercise or
representative learner/range rehearsal. Tests also cover full-play pass/miss and
source/impact/recovery fault paths across reset with exact canonical comparison.
