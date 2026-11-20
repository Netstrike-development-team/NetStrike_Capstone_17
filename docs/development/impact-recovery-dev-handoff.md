# Safe impact and recovery integration — #83

## Outcome and boundaries

The selectable full-play scenario connects identity, cloud, impact prevention,
marker-only file impact, recovery, a final brief and the 130-minute play end.
This is a **development integration**, not Cyber Range delivery acceptance.
The 15-minute briefing and 25-minute hotwash remain facilitated activities:
15 + 130 + 25 = the approved 2h50 session.

The previous identity-only and cloud-slice defaults/demos are unchanged.
The legacy ransomware demonstration, encryption, VM disks, real backups,
real customer files and external services are never invoked by this path.
No paid resource or new Python dependency is needed.

## Explicit opt-in and provisioning contract

Full play requires both the selected scenario and a dedicated disposable root:

```bash
# Operator creates this empty directory inside the approved lab filesystem.
mkdir -p /absolute/approved/lab/netstrike-disposable
export NETSTRIKE_IMPACT_ROOT=/absolute/approved/lab/netstrike-disposable
export NETSTRIKE_SCENARIO_PATH=orchestrator/scenarios/full-play.v1.json
```

These are deployment examples, not paths to use blindly. Patrick selects the
actual local lab location. Keep the existing portal tokens, allowed SSO origins,
identity-audit key and database settings. The cloud/recovery role is
`cloud_responder`; endpoint prevention uses `endpoint_responder`.
Secrets stay injected, never committed.

The root must already be an absolute real directory. First use requires it to
be empty; the runtime writes a versioned ownership marker and creates only the
new run's five synthetic originals, known-good copies and staging directory.
Later use validates the marker and run-directory structure. Broad root/home/repo
directories, symlink roots, unrelated contents and reused/unsafe run IDs are
rejected. An existing run is never silently adopted after process restart.

Only logical fixture IDs are accepted by HTTP actions. Users cannot supply a
filesystem path or variant. File inventory refuses traversal, symlinks,
hardlinks, unexpected entries and files over 64 KiB. No target outside the
approved run directory is modified.

Application startup **provisions decoys** when full play is explicitly selected.
Scheduled MSEL branches are reviewed execution requests, not previews.
Participant recovery and the developer CLI default to preview until explicitly
executed.

## Timeline and decisions

The full fixture preserves the combined slice's compressed timings:

| Item | Play time | Behavior |
| --- | --- | --- |
| PRE-03 | Before play | Verify decoy/backup hashes and arm only the synthetic pre-staged task |
| DP1 / DP2 / DP3 | 25 / 60 / 95 min | Existing identity and cloud decisions |
| MSEL-08 | 100 min | Actual blocked-access notification or synthetic claim, never invented transfer |
| DP4 | 110 min | Verify host isolation, persistence removal and task disablement |
| ACT-08A/B | DP4 result | Apply only the permitted marker variant |
| MSEL-09 | 115 min | Executive recovery and remaining-risk request |
| END-01 | 130 min | Freeze recovery/brief observations and end technical play |

PRE-03 makes `impact-task-01` active in **mock endpoint state**. There is no OS
process or actual scheduled task. Participants find its ID in the evidence and
use the existing `endpoint.process.stop` action. They also use
`endpoint.host.isolate` and `ad.persistence.remove` when supported by evidence.

Complete prevention passes DP4. No prevention creates five marker companions,
a benign exercise note, and moves the five decoy originals into run-owned
staging. Bytes are unchanged; known-good copies are untouched.
The blocked variant leaves originals available beside five harmless markers.

Partial prevention remains truthful: a stopped task is never rearmed to force
impact, even if the team misses isolation/persistence requirements.
Isolation alone does not stop a pre-staged local task. DP4 may miss while the
actual marker variant is blocked; those are separate observations.

DP4 selects the **prevention** branch. Recovery, checksum verification and
communication are assessed after impact and frozen at play end, not falsely
declared complete before recovery begins. No fifth decision checkpoint is added.

## Participant workflow

1. Read actual task/endpoint and file/hash evidence in **Disposable-file recovery**.
2. Apply supported endpoint prevention before DP4.
3. After impact, inspect available originals, unchanged hashes and marker count.
4. Enter the logical fixture ID from the evidence, never a path.
5. Leave **Preview only** checked for an initial request. It changes no files,
   does not run a checksum handler and cannot count as recovery verification.
6. Uncheck preview to execute decoy restore, then execute hash validation.
7. Submit confirmed scope/cloud record count, business impact, actions taken,
   remaining risk and at least two prioritized recommendations. Cite the real
   current-run recovery validation event.

The participant gets a submission receipt, not hidden grading checks.
No response target IDs are prefilled in the HTML. Staff see separate DP4 and
recovery observation previews. Report **quality**, chronology, recommendations,
remaining-risk reasoning and objective weighting still require #84/evaluator
review; nonempty fields alone are not proof of a good report.

### API

- `GET /api/participant/recovery`: copied logical inventories/hashes, actual
  task state and current-run audit; no server paths or verifier answers.
- `POST /api/participant/recovery/action`: exact
  `recovery.fixture.restore` or `recovery.health.validate`, logical fixture ID,
  idempotency key and strict boolean `dry_run` (default `true`).
- `POST /api/participant/recovery/brief`: bounded structured report, current-run
  evidence references, two or more recommendations; server-owned actor identity.
- `POST /api/facilitator/checkpoints/dp4`: staff-only, due and running, prepared
  source, healthy baseline and earlier DP2/DP3 resolution required.
- `POST /api/facilitator/impact/rollback`: one-use rollback of this run's
  successful impact, recorded as staff intervention. Revalidate afterward.

Recovery writes require `cloud_responder`; SOC/lead roles can inspect and submit
the report but cannot forge mutation privileges. There is no participant
`impact.marker.apply` or arbitrary action/path endpoint.

## Failures, stop, reset and restart

File operations capture exact snapshots. Partial marker/restore failure or
cooperative cancellation restores the previous decoy state before returning a
failure. Tests interrupt marker creation, fail restores and inspect outside
symlink/hardlink targets.

Emergency stop disables runtime adapters. Staff state remains readable even if
the fixture becomes unsafe, so a filesystem fault cannot remove the stop control.
Explicit reset uses a fresh control-only cleanup adapter after stop/completion;
it does not re-enable participant mutation.

Reset validates the new run destination **before** cleanup, restores/verifies the
old fixture, provisions a distinct new fixture, then changes controller identity.
Unsafe entries or corrupted backups block reset without advancing/admitting a
new run. Prior ledger/submission evidence and clean old decoys remain archived.
Reset never erases the root or other run directories.

Process restart is not supported as live state replay. Select a new safe run ID
and restore the previous run through the approved operator/snapshot workflow.
Application reset is not VM restoration; Patrick's clean snapshots/readiness
remain authoritative.

Missing/failed source or branch evidence blocks finalization as a platform fault.
Stop/pause and investigate; do not score missing telemetry as learner failure.
A missing/incorrect brief with otherwise observed play can end normally with
missed recovery/communication observations. Technical actions are denied after
completion; recovery observation results are frozen rather than rewritten.

## Evidence and demonstrations

Canonical sources: `marker-impact-simulator`, `marker-impact-action-adapter`,
`marker-impact-automation`, `impact-reset-controller`. Events share the global
sequence and exercise/run correlation, logical host `FILE01`, fixture ID,
phase `impact_recovery` and objectives LO4/LO5. They include unchanged-original
proof, before/after manifests, marker counts, restore/health observations,
rollback/reset and evaluator-only final review. Existing staff JSONL/CSV exports
include these events.

```bash
# Default: preview only, no provisioning or writes.
python -m orchestrator.impact_demo
# Execute only temporary five-decoy fixtures, restored and removed on exit.
python -m orchestrator.impact_demo --outcome blocked --execute
python -m orchestrator.impact_demo --outcome realized --execute
python -m orchestrator.impact_demo --outcome partial --execute
# Optionally retain an approved root and export to a NEW local ledger path:
python -m orchestrator.impact_demo --outcome realized --execute \
  --root /absolute/approved/lab/netstrike-disposable \
  --run-id demo-new-001 --events /tmp/impact-demo-new-001.jsonl
```

Expected before recovery: blocked = DP4 pass / 5 originals available; realized =
miss / 0 available but unchanged in staging; partial = miss / 5 available.
All three restore cleanly and finish at 7800 logical seconds. CLI summaries are
developer evidence, not learner or Cyber Range sign-off. Run IDs/event IDs differ;
fixtures, marker variants and checksums are deterministic.
Demonstrations use a declared fixed UTC clock, including ledger validation;
do not treat these replay timestamps as live source-freshness acceptance.
Normal portal runs use the actual clock and Patrick's lab NTP configuration.

## Team handoff

- Aya: runtime/API safety, local regression and defect fixes.
- Patrick (#102–#104): source ingestion, offline transfer of matching code,
  schemas/fixtures, approved disposable root permissions, snapshots and
  representative deployment/stop/reset rehearsals.
- Anna (#98–#100): final messages/scripts, participant wording, guides,
  browser/learner usability, briefing/hotwash and evaluator content.
- Ashley (#96/#97): dates, deployment coordination and acceptance tracking.

Live Splunk/VM acceptance, representative browser QA and final #84 scoring/AAR
are not claimed complete by this implementation.

## Local verification receipt (2026-10-01)

- Application, shared safety, identity, lateral-movement and script regression:
  432 passed, with four existing dependency/deprecation warnings.
- Separately collected legacy cloud module: 28 passed; impact module: 42 passed.
  Total: 502 passing tests. The legacy module suites are collected separately
  because their shared `tests` package names collide in a combined invocation.
- Changed production Python: Pylint 10.00/10 using the repository-style
  import/docstring exclusions and the common-adapter duplicate-code exclusion.
- Bandit: no findings across shared/orchestrator/dashboard and impact actions.
- Both portal scripts passed Node syntax checks; `git diff --check` passed.
- Preview CLI made no fixture writes. Blocked, realized and partial execution
  demos all restored unchanged decoys and completed the 130-minute play.
  A realized demo exported 130 schema-validated canonical events using its
  explicitly declared virtual clock; export refuses an existing destination.

These are local development checks, not browser, live Splunk ingestion,
air-gapped deployment or VM snapshot acceptance.
