# Reliable current-run evaluator review

The offline `/evaluator` page keeps human review, revision checks and current
exports aligned. It uses existing bearer roles, reports, append-only judgments
and archives. No rubric, rating scale, numeric-grade policy or approval is added.

## Inspect, draft, save and export

1. Connect with an evaluator/facilitator credential and load the current report.
   Other roles cannot read staff reviews or download them. Ratings are editable
   only after stopped/completed play; a stopped run is still partial.
2. Select an objective, inspect evidence and draft the judgment. Refresh retains
   the draft if the run and **selected objective's saved revision** are unchanged,
   even when other objectives/evidence changed. Selecting another objective loads
   its saved judgment as before; there are not separate drafts per objective.
3. A newer saved revision clears the stale draft and loads the recorded judgment
   with a notice. An observed reset or credential change clears the old private
   view/draft. Transient read failure retains the draft but disables save/export
   until a successful current inspection.
4. Record judgment once. The request freezes the run, objective and expected
   revision. Editing/another save is blocked while it is in flight; manual Refresh
   remains available. Old credential/run replies are discarded. A valid receipt
   confirms the revision and triggers a fresh report read.
5. If acknowledgment is lost, rejected or invalid, **do not assume the write
   failed**. Refresh and inspect the recorded revision before deciding to edit or
   submit again. There is no automatic retry, idempotent replay or automatic
   reconciliation of two reviewers' prose. Server revision/evidence rules remain
   authoritative; judgments append history and never alter scenario branches.
6. Download the current bundle/AAR after inspection. The browser pins the run and
   exact report's bundle SHA-256 and preserves raw server text. If play, a rating,
   archive audit or any other bundle input changed, export is refused: refresh
   and inspect again. Downloads resolved after a newer run/credential/snapshot
   was loaded are discarded. Filenames include the run and a short snapshot-hash
   prefix; that is a label, not a signature.
7. Keep approved staff exports outside restored VMs before application reset or
   hypervisor rollback. Capture/browse historical reviews through the existing
   [archive panel](run-review-archives.md). Current exports are not frozen archives,
   VM backups, calibration or range acceptance. Never share raw staff material
   with learners; use the existing participant-feedback projection instead.

Drafts exist only in page memory/fields; reloading/closing loses them. Nothing is
saved to browser local storage. No UI can guarantee delivery if the process or
network is stuck. Staff still follow the range's safety procedure.

## API scope and compatibility

`GET /api/evaluator/report`, `/exports/bundle.json` and `/exports/aar.md` accept
optional `X-Exercise-Run-ID`. The exports also accept optional
`X-Review-Bundle-SHA256`: exactly 64 lowercase hex characters from
`report.bundle_sha256` (or `bundle.content_sha256`). Scope check, bundle construction,
hash comparison and export serialization use one existing run lock. A changed
run/snapshot returns generic `409`; malformed/duplicate headers return `422`.
The private evaluator API is `Cache-Control: no-store`, including failures.

Legacy callers omitting headers still read latest authorized data but do **not**
gain stale-run/snapshot protection. Initial report refresh deliberately reads the
current run, allowing reset discovery; browser downloads use both guards. Headers
cannot grant roles or make running play reviewable. Judgment/archive POSTs retain
their explicit body run/revision/hash checks. Historical reads use immutable
archive IDs, independent of current-run scope. No report/bundle version changes.

SHA-256 is a consistency guard, **not** authenticity proof. Matching it does not
establish sources, identity provenance, calibration or client acceptance.
The guards select a snapshot while the request is handled, not a promise that
the server cannot change later while its response travels to the browser.

## Verification and owner handoff

```sh
python -m pytest dashboard/tests/test_evaluator_exports.py -q
node --test dashboard/tests/*.test.mjs
```

Local API checks cover the three reads, privacy/cache/legacy behavior, duplicate,
invalid/stale run and snapshot guards, same-run revisions, reproducible bundle/AAR
bytes and reset serialization. Dependency-free Node tests execute the model and
actual page bindings: draft preservation/conflict, lost acknowledgment, credential/
reset races, raw pinned downloads and no repeated writes. Deployment preflight and
the 24-case rehearsal fingerprint the new asset. This is not browser visual QA,
non-author usability or live range evidence.

Aya owns application integration/defects. Anna validates operational wording,
reviewer usability, evaluator/solution guides and rubric calibration (#100).
Patrick verifies deployed role separation, concurrent access, export preservation
and live rehearsals (#104). Ashley coordinates dates/client acceptance. Their
ownership is unchanged; no new dependency, service or hosted deployment is added.
