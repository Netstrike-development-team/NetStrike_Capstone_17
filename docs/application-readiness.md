# Local application readiness and guarded start

The authenticated portal now checks the local application before preparation
and again before play. This prevents staff from starting a dirty baseline, a
missing action handler or failed setup and discovering it only during delivery.
It is **not** a Cyber Range readiness certificate or permission to admit learners.

## Staff workflow

1. Obtain the deployment's facilitator or technical-operator bearer credential.
2. Inspect `GET /api/facilitator/readiness`. This is read-only and not cached.
3. Use the existing Prepare control. Preparation is audited and allowed only if
   the inspected local baselines match. Its result is checked again afterward.
4. Complete Patrick's external environment checks and the facilitator's admission
   decision separately. None are automatically marked passed by this API.
5. Use Start. It always rechecks the current state, not a previously saved report.
   Existing clients that call only Start are preserved: the service safely
   prepares pending setup first, verifies the result, then starts the clock.

Staff may inspect the report without a browser:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $NETSTRIKE_STAFF_BEARER" \
  http://127.0.0.1:8000/api/facilitator/readiness
```

Use the actual approved portal address and staff credential. The command does
not start an instance. Do not put real credentials into source files or evidence.
Participant, evaluator, simulated-user and capture-service credentials cannot
read this report or prepare/start play. Public `/health` remains liveness only.

## Report meaning

`scope` is always `local_application_only`. `ready_to_prepare` means these local
checks matched; `ready_to_start` additionally requires every pre-exercise item
to have been delivered successfully. `blockers` lists safe technical check IDs.
An inspection error is a blocker, never an assumed pass; exception strings,
server paths and credentials are not included in the report.

| Check | What is inspected |
| --- | --- |
| `pre_play_state` | Ready controller, zero elapsed play time, no resolved checkpoints. |
| `required_handlers` | Every action in the loaded scenario has a callable registered handler. |
| `preparation_progress` | Setup items are pending or delivered, not skipped, failed or stuck ready. |
| `identity_baseline` | Pinned synthetic identities, factors, sessions, credential versions and MFA state. |
| `endpoint_baseline` | Reviewed hosts, accounts, process and artifact state. |
| `simulation_baseline` | Baseline/history flags agree with setup delivery, with no later attack transitions. |
| `sso_baseline` | No residual local sign-in workflow or generated session. |
| `scheduled_mfa_baseline` | No pending challenge or challenge history before play. |
| `submissions_empty` | No learner submissions in the current pre-play run. |
| `identity_audit_empty` | No residual identity-capture interactions in the current run. |
| `event_ledger` | Valid, contiguous, current-run events agreeing with the live sequencer. |
| `cloud_baseline` | Enabled mock-cloud state matches its baseline, without residual audit or assessment. |
| `impact_baseline` | Enabled disposable fixture hashes match and recovery/impact state is clean. |

The full-play PRE-03 intentionally arms the synthetic impact task. A successfully
delivered PRE-03 is therefore expected to leave that one process active; the gate
does not require it to be inactive after approved setup. It also does not reapply
setup to conceal changes made after preparation. Repeated Prepare is supported
only when local state still agrees with the already-delivered setup.

An SSO demonstration or identity capture performed before play dirties this
pre-play baseline. Stop and reset into a new run before starting the actual
exercise. Demonstrations should not share the delivery run ID.

## Failures and evidence

Prepare/Start return HTTP 409 with blocker IDs if local checks fail. No play clock
starts. Failed preparation remains visible in the existing MSEL state; a later
Start cannot bypass it. Diagnose the failed item or drift, preserve evidence,
then use the existing Stop and Reset procedure with a new run ID. Do not delete
evidence or manually mark failed items delivered to bypass the gate.

The controls persist `exercise.readiness.checked` before proceeding, with the
server-authenticated actor, current run and report. These events are staff-only
and appear in canonical exports; they are not participant signals or ratings.
An audit-write failure blocks the transition. A ledger mismatch or unreadable
database blocks without attempting to append into potentially corrupt evidence.

SQLite persists events, not reconstructable live controller/adapter state. After
a process restart, reusing an existing run ID is rejected by this gate rather
than pretending that a fresh in-memory baseline resumes the old exercise.
Preserve the old database and fixture evidence, and begin a separately identified
fresh run through the approved restoration workflow. Automatic crash-resume is
not implemented by this change. A passing read-only ledger inspection is not a
database write test; actual audited transitions must persist before proceeding.

## External checks and responsibilities

`external_readiness_verified` is always false, and all `external_checks` are
`not_checked`. The report cannot verify approved VM addresses/topology, Splunk
ingestion and role access, DNS/NTP, VM services or snapshot restoration, staff
access to emergency stop, or facilitator admission sign-off. These remain
Patrick's environment/readiness work and the team's release acceptance under
#79, #103, #104 and #86. No 20-minute Ansible reset target is introduced.

Aya owns this code-level gate. The strict full-play CI workflow runs the readiness
tests and rehearses normal paths through this service boundary. The deliberate
missing-impact-source rehearsal uses a fixed low-level fault injection to test
downstream fail-closed grading; it is not an HTTP bypass exposed to learners.
