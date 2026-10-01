# Mock-cloud exercise stage — developer handoff (#82)

## What works and how to select it

The existing Python mock is now connected to an identity + cloud scenario,
authenticated investigation/response tools, canonical evidence and DP3.
It is **not AWS**: no cloud SDK, Internet access, paid account, reusable key,
real customer data or external transfer is involved.

The original identity-only fixture remains the default, with its existing demo
timing. Explicitly select the new combined fixture:

```bash
export NETSTRIKE_SCENARIO_PATH=orchestrator/scenarios/cloud-slice.v1.json
```

Keep the portal token, audit key, allowed origins and database configuration from
`dashboard/README.md`. Provision a server-owned `cloud_responder` token for
cloud mutations; never commit/display tokens. Other participant roles can
investigate and submit assessments but cannot acquire cloud write privileges
by changing JSON. No new dependency was added. Transfer matching source,
schemas and fixtures with the existing wheel bundle. The legacy
`cloud_exfil.py` is not invoked by this path.

## Approved compressed timeline

| Item | Play time | Observable event |
| --- | --- | --- |
| DP1 | 25 min | Existing identity classification |
| DP2 | 60 min | Existing identity/endpoint containment |
| ACT-05 | 65 min | Service-key authentication, enumeration, one-object access |
| MSEL-06 | 70 min | Finance reports export delay |
| ACT-06 | 75 min | Designated policy-change attempt and up to five records |
| MSEL-07 | 85 min | Legal requests evidenced data scope |
| DP3 | 95 min | Verify key/policy state and submitted assessment |
| ACT-07A/B | DP3 result | Bulk request evaluated against current controls |

The new fixture retimes its copied identity portion to match the approved MSEL
without changing the older identity demo. This is an **integration slice**, not
the complete 2h50 exercise. Impact/recovery, DP4 and final brief remain #83/#84.
The run stays active after DP3; explicitly stop/reset development demos.
Full delivery must preserve 15-minute briefing, 130-minute play, 25-minute hotwash.

## Learner workflow and server boundaries

1. Open the participant console with the injected role token.
2. Refresh **Mock-cloud investigation**. Review actual current-run audit,
   synthetic principal/key/roles, bucket policy and 25 object metadata entries.
3. Cite cloud audit event IDs, not guessed identifiers or threat-actor claims.
4. Preserve the pre-remediation bucket state/audit if needed.
5. Revoke the key (or disable its owner), restore the approved policy, and verify.
6. Submit principal, confirmed record count, conclusion and audit event IDs.
   Receipt does not expose grading answers.
7. Staff resolve DP3 when due; learners inspect the subsequent bulk result.

Participant target inputs are blank. Read-only tools expose current/observed
facts, not scores, branch criteria or facilitator feeds. Staff get a separate
DP3 verifier preview and resolution control.

| Action | Exact target | Required participant role |
| --- | --- | --- |
| `cloud.evidence.preserve` | `cloud_bucket:simcorp-customer-exports` | cloud responder |
| `cloud.key.revoke` | `cloud_key:svc-cloud-backup-key-01` | cloud responder |
| `cloud.principal.disable` | `cloud_principal:svc-cloud-backup` | cloud responder |
| `cloud.policy.restore` | `cloud_bucket:simcorp-customer-exports` | cloud responder |

All changes use the shared adapter's exact-target/role/run-state policy,
dry-run, idempotency, cancellation and rollback metadata. Although the module
adapter also supports facilitator authority, participant HTTP actions accept
participant roles only; staff use reviewed timeline/checkpoint controls.

- `GET /api/participant/cloud`: copied current state/audit, read-only.
- `POST /api/participant/actions`: role-bound allowlisted remediation.
- `POST /api/participant/cloud/assessment`: bounded response citing cloud events
  from the current run; grading checks are not returned.
- `POST /api/facilitator/checkpoints/dp3`: staff resolution only when due.
- Existing staff JSONL/CSV exports include cloud, action and checkpoint evidence.

## Actual access always wins over narrative

Normal ACT-05/06 activity confirms five synthetic records. Correct key/policy
containment and supported assessment pass DP3 and block bulk retrieval.
No containment allows 25 records and a labelled synthetic extortion **claim**.

A missing/incorrect assessment can miss DP3 even when a defense worked.
The adverse attempt still checks actual permissions: revoked key, disabled
principal or restored policy blocks access. It never invents 25-record exposure
or an extortion message after denial. Preemptive key/principal containment may
produce zero records; use the actual count rather than manufacturing five.

Current `confirmed_count` and matching `cloud.object.accessed` events are
authoritative. Every cloud event declares `external_transfer_observed=false`.
Mock access and an extortion claim do not prove external exfiltration.

Sources: `mock-cloud-simulator`, `mock-cloud-automation`,
`mock-cloud-action-adapter`. They share exercise/run IDs and global sequence,
principal/key/bucket correlation, reserved source `203.0.113.77`, logical host
`CLOUD01`, phase `cloud`, objective `LO3`. Object audit includes cumulative
synthetic record IDs/count/bytes.

## Safety, persistence and reset

- Only active-run Python memory changes. No external cloud, shell command,
  file download or customer database is touched.
- State lasts for the active process/run, **not across process restart**.
  SQLite archives ledger/submissions but does not restore live mock state.
  An interrupted process requires a new clean run.
- Pause blocks learner mutation. Emergency stop disables cloud adapters and
  future steps. Staff cannot deliver a DP3 branch before its verified outcome.
- Failed/skipped source steps block grading as a platform fault rather than a
  participant miss. Pause, investigate and record any fallback/deviation.
- Evidence preservation freezes one copied state/audit snapshot; later
  remediation or preservation does not overwrite it.
- Application reset rebuilds objects, controls, exposure, audit, preserved
  evidence and assessment. Prior ledger/submissions remain archived; old
  event IDs cannot support a new assessment.
- Application reset is not VM restoration. Cyber Range snapshots and Patrick's
  readiness workflow remain authoritative.

## Repeatable local demonstrations

From the repository root with existing dependencies:

```bash
python -m orchestrator.cloud_demo --outcome contained
python -m orchestrator.cloud_demo --outcome full
python -m orchestrator.cloud_demo --outcome partial
# Optional canonical ledger; use a new local path for each demonstration.
python -m orchestrator.cloud_demo --outcome contained --events /tmp/cloud-contained.jsonl
python -m pytest orchestrator/tests dashboard/tests modules/06-cloud-exfil/tests shared/tests -q
```

Expected: contained = DP3 pass / 5 records / blocked; full = miss / 25 records /
claim; partial = miss / 5 records / blocked. Logical outcomes are deterministic;
event IDs are run-specific. No sleeps or network calls are needed.

## Remaining acceptance and ownership

- **Aya:** development integration, local tests, safety and defect fixes.
- **Patrick (#102/#104):** live Splunk ingestion/searches, role separation,
  volume measurement and clean snapshot rehearsals. Valid local JSONL is not
  evidence of live Splunk delivery.
- **Anna (#98–#100):** final inject/role-player wording, guide alignment and
  representative participant/browser usability.
- **Ashley (#96/#97):** coordinate deployment dates and acceptance follow-up.

No new spending/procurement is needed for this development slice.

## Local verification receipt — October 1, 2026

- 374 shared/orchestrator/portal/profile/identity/endpoint/bundle regression tests.
- 28 module-06 tests and 39 module-07 tests, run separately from their module
  directories because the legacy test packages collide in a single collection.
- 441 tests passed across those suites; four existing/dependency deprecation
  warnings in the broader regression run.
- Changed production Python lint passed; Bandit found no issues in the checked
  shared/runtime/portal/cloud-action code; both portal scripts passed Node syntax
  checks; `git diff --check` passed.
- All three local demo outcomes verified; contained JSONL export validated.
- No browser was available through the UI tool for visual verification.
  API/static checks do not replace representative browser/learner rehearsal.
- No live Splunk, Cyber Range VM or snapshot acceptance is claimed.
