# Module 6: Mock-cloud containment

## Purpose

This module supplies the state and containment controls for the Silent Spider
mock-cloud phase. It does not connect to AWS or any other external service.

- `cloud_actions.py` is the authoritative, deterministic exercise-control
  surface. It changes only run-scoped Python state through the shared safe
  action adapter.
- `cloud_exfil.py` is a legacy standalone demonstration that creates local
  synthetic output. It is not an exercise-state authority or an authorized
  controller mutation path.

The reference state can later be replaced by a CITEF-hosted mock service while
retaining the same action policy, identifiers, results, and audit events.

## Approved exercise objects

| Object | Identifier | Baseline |
| --- | --- | --- |
| Service principal | `svc-cloud-backup` | enabled and synthetic |
| Opaque key ID | `svc-cloud-backup-key-01` | active; no reusable key material is stored |
| Bucket | `simcorp-customer-exports` | 25 synthetic records and the approved policy hash |

`MockCloudState.adverse_fixture()` represents the full-exposure branch: the
bucket has the expanded exercise policy, bulk access is permitted, and exactly
25 synthetic record IDs are marked accessed. This is exposure evidence, not
real customer data.

## Registered safe actions

The following actions require the `cloud_responder` or `facilitator` role, a
`running` exercise, and the exact target shown:

| Action | Exact target | Effect |
| --- | --- | --- |
| `cloud.key.revoke` | `cloud_key:svc-cloud-backup-key-01` | revokes the pre-staged mock key |
| `cloud.principal.disable` | `cloud_principal:svc-cloud-backup` | disables the principal and atomically revokes its owned keys |
| `cloud.policy.restore` | `cloud_bucket:simcorp-customer-exports` | restores the approved policy hash and denies bulk access |

Exercise-control actions are limited to a `technical_operator` or
`facilitator`:

- `exercise.cloud.reset` restores the approved fixture only when the run is
  `stopped` or `resetting`.
- `exercise.cloud.readiness.validate` reports `baseline_mismatch` unless all
  principals, keys, buckets, policies, and exposure evidence match baseline.

Every mutation produces a one-use rollback snapshot. The shared adapter also
enforces correlation, role, exact target, run state, parameters, timeout,
dry-run, idempotency, cancellation, result validation, and audit events.

## Exposure and containment verification

`MockCloudState.access_decision()` is a read-only verifier for future scenario
engine integration. It distinguishes `principal_disabled`, `key_revoked`,
`key_principal_mismatch`, and `policy_denied`, allowing the contained branch to
produce a defensible blocked-access event without making a network request.

The adapter never stores a secret or token. Key IDs are opaque exercise
identifiers only, and all record identifiers are explicitly synthetic.

## Development

From the repository root:

```bash
python -m pip install -r modules/06-cloud-exfil/requirements.txt
python -m pytest modules/06-cloud-exfil/tests shared/tests -q
```

Tests cover key and principal containment, approved-policy restoration,
exposure fixtures, access decisions, role/target denial, dry-run, idempotency,
rollback, reset, readiness, and event validation.
