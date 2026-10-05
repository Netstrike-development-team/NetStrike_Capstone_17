# Offline staff operations

The existing `/facilitator` and `/evaluator` pages now surface local readiness,
delivery-clock diagnostics and immutable run-review archives. They use the
existing offline application and configured bearer credentials: no new service,
licence, CDN, Internet access or JavaScript package installation is needed.

## Before and during play

1. Connect with the deployment's **facilitator** or **technical_operator** token
   at `/facilitator`. Tokens must not appear in demo recordings or evidence.
2. Read **Local application readiness**. Failed inspections are blockers, not
   assumed passes. Prepare is available when the local baselines match; Start
   is enabled only after preparation is complete. The backend always rechecks.
3. Separately complete Patrick's VM/Splunk/DNS/NTP/snapshot checks and the
   facilitator admission decision. The page explicitly says these are **not
   verified**. Start's confirmation reminds staff; it does not record external
   approval or certify readiness.
4. Check **Automatic delivery health**. Normal lifespan-driven play advances
   automatically. Manual rehearsal advance is tucked into a separate disclosure;
   it skips exercise time and is not proof of realistic timing or performance.
5. Pause/resume, checkpoint resolution and manual inject controls are enabled
   only for their relevant state. A technical operator cannot make the
   facilitator-only simulated MFA decision. Normal baseline changes during play
   are not labelled as pre-play failures.

Clock faults/staleness disable ordinary delivery controls. Stop, terminal reset
and available marker rollback remain accessible. Enter a safety/platform reason
and press **Emergency stop**: there is no extra confirmation prompt. The button
stays available while another ordinary request is awaiting a response, or when
a transient state read fails after the current run was authenticated. It does
not bypass server locks, cancel a stuck handler, guarantee audit persistence or
replace the Cyber Range emergency-stop procedure if the process is unreachable.
Inspect the distinct cleanup/audit diagnostics; never infer success from silence.

Private snapshots/drafts clear on reconnect or observed run changes. Delayed
responses cannot repopulate another credential's view. A failed read displays
unavailable health, not a cached healthy certificate. Controls with uncertain
outcomes are **not automatically retried**: refresh and inspect first.

## Finish review, capture and reset

1. Stop or complete play. Finish human objective judgments in the existing
   current-run evaluator form; capture does not fill missing ratings or calibrate
   the rubric. Technical operators cannot access evaluator archives.
2. At `/evaluator`, expand **Saved run reviews** and choose **Load current capture
   preview**. Review the run/state and
   counts, then **Capture reviewed run**.
   The request freezes the inspected run ID and bundle SHA-256. A changed run or
   uncaptured stale hash is rejected by the server.
3. If capture is not confirmed, inspect the archive list and use **Retry same
   capture**. The exact run/hash is retained. It never silently previews another
   hash after a lost acknowledgment. Explicitly replacing an uncertain preview
   requires a warning confirmation; later corrections can legitimately produce
   a separate capture.
4. Reload/page through saved captures in capture order (ten per page). **Show
   saved review** is a separate read-only panel: it never loads historical ratings
   into the current editable form. Download bundle, AAR or events from a listed
   capture. Bundle/JSONL text is preserved without parsing/reserializing it.
5. Export staff evidence to approved storage **outside restored VMs**. Archives
   live in the portal SQLite database and can disappear on hypervisor rollback.
6. Reset from `/facilitator`, optionally supplying a new unused run ID. Confirm
   the application-reset warning. The existing server archives terminal play
   before reset and refuses reset if capture fails. A success receipt identifies
   the prior run and archive. This is not VM restoration or a twenty-minute reset
   promise. Recheck local and external readiness before another session.

Capture boundaries exclude the archive's own audit, later cleanup and later
corrections. Reports remain provisional where appropriate. Raw staff exports
contain answer/rating material and human prose; do not share them with learners.
See [archive limits](run-review-archives.md) and [clock recovery](exercise-clock.md).

## API compatibility and stale-page guard

Browser facilitator commands and current-run event exports send
`X-Exercise-Run-ID` with the inspected run. The server validates it and holds the
existing run lock across the scope check and operation/serialization. A stale
run is a generic `409`; malformed/duplicate headers are `422`. Authentication,
role restrictions and existing lifecycle checks still apply. The header is
optional for legacy CLI/integration callers: those callers do **not** gain stale
page protection unless they send it. Support replies and archive capture retain
their existing explicit run/body contracts. Historical archive reads deliberately
address immutable IDs, not the new current run.

## Verification and owner handoff

Dependency-free Node tests execute real client models/render/mount bindings with
DOM test doubles. API tests cover every guarded staff operation, exports, role
privacy, fresh post-fault reset diagnostics and control/reset locking. Full-play
rehearsal manifests fingerprint both new modules. These are local regressions,
not browser visual/usability testing, real Splunk proof or live range acceptance.

- Aya owns this interface/API integration and application defects.
- Anna tests wording, operation flow, realistic timing and rubric usability with
  a non-author facilitator/evaluator; final content/calibration remain hers.
- Patrick proves deployed access, supervised delivery under load, evidence export
  outside restored VMs and snapshot recovery. His Ansible/Splunk scope is unchanged.
- Ashley coordinates the rehearsal, admission and client acceptance decisions.
