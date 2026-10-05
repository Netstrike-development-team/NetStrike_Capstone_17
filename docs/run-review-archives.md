# Staff run-review archives

The portal preserves a frozen review snapshot **before application reset**.
Authorized staff can later list and download that snapshot while a fresh run is
active. It includes the original v1 review bundle: run/scenario/checkpoint scope,
canonical events, learner submissions and recorded evaluator revision history.
Provisional reviews remain provisional; missing ratings are never made into zeroes.

This is local application retention, not a backup service, crash-resume feature,
VM snapshot guarantee, calibrated grading or Cyber Range acceptance. No new tool,
licence or Internet connection is required.

## Capture and retrieve

The `/evaluator` **Saved run reviews** section provides terminal capture preview,
explicit capture, paginated history, separate read-only reports and raw downloads.
Unconfirmed capture retains the exact run/hash for retry, not a silently refreshed
hash. See [staff operations](staff-operations.md) for the complete browser workflow.

The existing facilitator Reset endpoint automatically captures stopped/completed
play before any reset mutation or transient-audit cleanup. Its response adds
`reset.review_archive_id`. Capture failure blocks reset without deleting old
events or submissions. Invalid reset state/target is rejected before capture.

Evaluators and facilitators can also capture a stopped/completed run explicitly:

1. Read the current `GET /api/evaluator/exports/bundle.json`.
2. Send `POST /api/evaluator/archives` with only:

   ```json
   {"run_id": "THE_CURRENT_RUN", "expected_bundle_sha256": "THE_BUNDLE_CONTENT_SHA256"}
   ```

3. Save the returned `metadata.archive_id`. A changed run or uncaptured, stale
   bundle hash is refused. Repeating an already-captured exact hash in the same
   terminal run returns `already_captured`, without another event or reassigned
   attribution. Use a fresh bundle hash to capture later evaluator corrections.
4. List previous captures with `GET /api/evaluator/archives`. The page contains
   metadata only, in capture order—not event occurrence order. Use `limit` (1–100,
   default 50) and `after_sequence` with the returned `next_sequence`; `has_more`
   indicates another page.
5. Download an archive using its opaque UUID:

   | Endpoint | Content |
   | --- | --- |
   | `GET /api/evaluator/archives/{id}/bundle.json` | Original validated offline review inputs |
   | `GET /api/evaluator/archives/{id}/report` | Structured report reproduced from the frozen bundle |
   | `GET /api/evaluator/archives/{id}/aar.md` | Markdown AAR with review history and improvements |
   | `GET /api/evaluator/archives/{id}/events.jsonl` | Canonical event prefix through the capture cutoff |

All reads require evaluator or facilitator credentials and return `no-store`.
Participants, simulated users and capture services cannot read or create archives.
Technical operators can invoke Reset and thereby capture its audit record, but
cannot use the review archive endpoints. Internal in-process resets are explicitly
attributed to `application-reset`/`system`, not an invented human facilitator.
Actor identity and role always come from the server, never the capture body.

Current-run reports, learner signals, submissions and feedback continue to use
the fresh run only. Archived reports are read-only; there is no archive edit,
delete or historical-rating endpoint. Finish ratings before reset, or keep the
run stopped while reviewers make corrections and capture a later snapshot.

## Exact capture boundary and audit

Metadata records the terminal state, scenario, actor, capture reason/time,
event/submission counts, last included event sequence, bundle digest and review
completeness. `capture_boundary` is
`terminal_review_snapshot_before_archive_audit`.

The bundle is frozen first. Its `evaluation.archive.created` audit event is the
next old-run sequence. SQLite commits the snapshot and this canonical audit in
one transaction, or commits neither. The audit event is staff-only and includes
the archive UUID, captured digest and cutoff. It does not embed another copy of
the bundle. A failed transaction cancels its sequence reservation only after the
service confirms the original ledger is unchanged; unreadable or uncertain
persistence remains fail-closed.

The frozen snapshot **does not contain its own archive-created event, later
reset/restoration cleanup events or later evaluator corrections**. Those events
remain in SQLite's original ledger. This deliberate boundary freezes play/review
evidence rather than pretending it contains every event emitted after capture.
The full local rehearsal exporter still exports the original ledger after reset;
its JSONL is therefore longer than the pre-reset archive prefix.

## Integrity, storage and recovery limits

- Storage migration is additive: a new archive table/index and immutability
  guards are created without replacing old tables or events. Old unarchived runs
  are not retrospectively reconstructed or backfilled.
- Snapshots are limited to 20 MiB, matching the offline report tool's input limit.
  List reads validate one bounded snapshot at a time, not a whole page of large
  bundles simultaneously. Invalid metadata, digest, event correlation, missing
  audit or incompatible bundle/rubric versions fail verification.
- Archives are immutable through the application and SQLite UPDATE/DELETE
  guards. These are not cryptographic guarantees against a database administrator.
  SHA-256 detects modification, not authenticity, signing or external acceptance.
- File-backed SQLite retains snapshots across application restarts. An in-memory
  developer store does not. Reading an archive does not resume its old runtime.
- If validation or persistence fails, preserve the database and raw ledgers,
  diagnose the failure, and retry after repair. Do not delete evidence or bypass
  archive safeguards to force reset. Corrupt snapshots are not served as valid.
- **A hypervisor clean-snapshot restore can erase this database and its archives.**
  Export evidence to Cyber Range-approved storage outside restored VMs before
  reverting them. Patrick owns the actual storage, snapshot and retention checks.
  Application archives do not fulfil the required range rehearsal/restore tests.
- Staff exports contain answer/evaluation material and free text. Use synthetic
  identities, inspect prose for sensitive information and never hand raw archives
  to participants. Key redaction cannot sanitize arbitrary prose automatically.

Downloaded bundles remain compatible with the existing read-only report command:

```sh
python scripts/generate_aar.py archived-bundle.json
```

Anna retains rubric/content review and evaluator calibration; Patrick retains
environment evidence and release acceptance; Ashley coordinates client decisions.
Aya owns this archive implementation and its strict portal/full-play regressions.
