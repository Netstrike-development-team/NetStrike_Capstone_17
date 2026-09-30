# NetStrike Safe Action Adapter Contract v1

**Schema:** [`schemas/action.v1.json`](../schemas/action.v1.json)

**Implementation:** [`shared/actions.py`](../shared/actions.py)

**Status:** v1.0.0 design and reference enforcement layer

## Purpose

Every state-changing learner, facilitator, reset, or automated scenario action
must cross this boundary. Modules expose handlers; they do not authorize their
own callers or write directly to exercise state from portal/controller routes.
The contract is CITEF-neutral: environment targets come from the approved
baseline manifest and are registered at startup.

## Required controls

Each `ActionDefinition` registers one stable action ID with:

- explicit permitted roles, targets, and run states;
- a maximum timeout and parameter validator;
- expected effects, a rollback method, handler, and rollback handler; and
- an exercise phase used for normalized audit events.

`SafeActionAdapter.execute` validates and redacts the request before enforcing
run correlation, registration, fail-safe state, run state, role, exact target
allowlisting, timeout policy, and parameters. Denial is the default.

Every request has an idempotency key scoped to its run. Replaying the same
operation returns the stored result without repeating effects. Reusing a key
for different inputs is denied as `idempotency_conflict`.

Dry-run is the default in `make_action_request`; it performs every policy check
but never invokes the handler. Handlers receive an `ExecutionControl` and must
call `checkpoint()` before each external/state-changing step. Backend clients
must also apply the registered deadline to network/process operations.

## Audit sequence

The adapter emits event-contract-v1 records for:

1. `action.requested`;
2. `action.authorization.granted` or `action.authorization.denied`;
3. `action.execution.started`;
4. `action.execution.completed` or `action.result.replayed`;
5. `action.rollback.completed` when applicable; and
6. `action.fail_safe.activated` for an emergency stop.

Events inherit the exercise/run context, include the request UUID as a
correlation ID, and carry the shared non-destructive safety marker. Result
records state whether effects occurred and retain rollback support/method/token
metadata without retaining secrets. Successful handler metadata is redacted and
included in the completion event's `data.metadata`, allowing manifests and
other non-secret evidence to remain auditable without expanding the result
schema.

## Roles and lifecycle

Action definitions use the role identifiers from the exercise charter, such as
`identity_responder`, `endpoint_responder`, `cloud_responder`, `facilitator`,
and `technical_operator`. Portal authentication maps users to these identifiers
server-side; client-supplied roles are never trusted without authentication.

The scenario engine supplies the authoritative run-state callback. An action
must list each allowed state explicitly. A fail-safe stop marks the run stopped,
signals cooperative cancellation to current handlers, blocks new actions, and
leaves existing evidence intact. Only facilitator or technical-operator roles
may invoke a stored rollback through the reference adapter.

## Integration rule

Identity, endpoint/AD, mock-cloud, marker-impact, and reset implementations must
register adapters at controller startup. Their HTTP/CLI/UI entry points submit
action requests to the shared adapter and display the returned outcome code.
No module may add a separate privileged mutation path.

Initial recommended IDs:

| Area | Action IDs |
|---|---|
| Identity | `identity.session.revoke`, `identity.factor.remove`, `identity.account.disable`, `identity.credential.reset` |
| Endpoint/AD | `endpoint.host.isolate`, `endpoint.process.stop`, `ad.account.disable`, `evidence.artifact.preserve` |
| Mock cloud | `cloud.key.revoke`, `cloud.principal.disable`, `cloud.policy.restore` |
| Impact/recovery | `impact.marker.apply`, `recovery.fixture.restore`, `recovery.health.validate` |
| Control/reset | `control.fail_safe.activate`, `exercise.run.reset`, `exercise.readiness.validate` |

## Example

```python
request = make_action_request(
    exercise_id="silent-spider",
    run_id="run-001",
    actor=entity("participant", "learner-01", role="identity_responder"),
    action_id="identity.account.disable",
    target=entity("identity", "sarah"),
    idempotency_key="DP1-disable-sarah",
    parameters={"confirm": True},
    dry_run=False,
    timeout_seconds=20,
)
result = adapter.execute(request)
```

## Acceptance boundary

The reference tests prove schema rejection, fail-closed authorization, exact
allowlisting, run correlation, parameter and timeout policy, dry-run behavior,
idempotent replay/conflict, fail-safe blocking, event emission, redaction, and
authorized rollback. Concrete module adapters must add tests for their own
state, backend timeout, partial-failure rollback, and reset behavior.
