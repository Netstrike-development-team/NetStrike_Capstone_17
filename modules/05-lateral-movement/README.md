# Module 5: Endpoint and Active Directory response

## Purpose

This module supplies the endpoint and directory state used by the Silent Spider
blue-team exercise. It has two deliberately separate surfaces:

- `endpoint_actions.py` is the authoritative, deterministic exercise-control
  surface. It changes only run-scoped Python state and is safe to call from the
  scenario engine.
- `ad_enum_simulated_escalation.py` is a legacy LDAP audit/evidence generator.
  It is not an authorized mutation path and is not used by the action adapter.

No action in the reference adapter changes a real workstation, directory,
account, group, or process. A CITEF-specific implementation can replace the
state handlers later while retaining the same action policy and audit contract.

## Exercise state

The clean fixture contains the exact allowlisted scenario objects:

| Object | Clean state | Exercise use |
| --- | --- | --- |
| `FIN-WS01` | reachable, controller-visible, not isolated | compromised workstation |
| `FIN-WS01-discovery-bundle` | not yet preserved, fixed SHA-256 | forensic evidence |
| `svc-print-sync` | absent and disabled | adverse-branch AD persistence |
| `impact-task-01` | stopped on `FIN-WS01` | simulated impact process |

`EndpointAdState.adverse_fixture()` deterministically creates the branch in
which `svc-print-sync` exists in `SimCorp-Server-Operators` and
`impact-task-01` is active.

## Registered safe actions

Participant/facilitator response actions are allowed only while the exercise is
`running` and only against the exact targets below:

| Action | Exact target | Result |
| --- | --- | --- |
| `endpoint.host.isolate` | `host:FIN-WS01` | disables the simulated remote path while retaining controller visibility |
| `evidence.artifact.preserve` | `evidence_artifact:FIN-WS01-discovery-bundle` | marks the discovery bundle preserved |
| `ad.account.disable` | `directory_account:svc-print-sync` | disables the adverse-branch account |
| `ad.persistence.remove` | `directory_account:svc-print-sync` | removes the synthetic account and group membership |
| `endpoint.process.stop` | `process:impact-task-01` | stops the simulated impact process |

Exercise-control actions are restricted to a `technical_operator` or
`facilitator`:

- `exercise.endpoint.reset` restores the clean fixture only in `stopped` or
  `resetting` state.
- `exercise.endpoint.readiness.validate` fails with `baseline_mismatch` when
  any endpoint/AD section differs from the clean fixture.

Every mutation produces a one-use rollback snapshot. The shared safe-action
adapter also enforces roles, target allowlists, run state, timeout, dry-run,
idempotency, correlation, fail-safe cancellation, event emission, and result
schema validation.

## Legacy LDAP evidence generator

`ad_enum_simulated_escalation.py` can perform read-only lab LDAP enumeration
and export user, group, and computer audit CSVs. Its staged privilege changes
are log messages only. It must not be treated as an endpoint/AD controller.

If a facilitator explicitly runs the legacy tool in an approved lab, install
the declared requirements and provide a lab-only credential through
`NETSTRIKE_AD_PASSWORD`. The module never installs packages or requests a
password at import time.

## Development

From the repository root:

```bash
python -m pip install -r modules/05-lateral-movement/requirements.txt
python -m pytest modules/05-lateral-movement/tests shared/tests -q
```

The endpoint action tests cover containment, evidence preservation, safe
handler failure, target denial, idempotency, rollback, reset, readiness, and
event-contract validation.
