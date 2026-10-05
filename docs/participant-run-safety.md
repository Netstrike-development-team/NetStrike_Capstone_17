# Learner run boundaries and reset safety

The offline `/participant` console binds response actions and submissions to the
exercise run it last inspected. This extends the existing staff run guard; it
does not change the storyline, grades, credentials, allowed targets or roles.

## Learner behavior

Connect and successfully load the current exercise before acting. Containment,
initial assessment, intrusion timeline, cloud assessment, recovery actions and
the final incident brief carry that run's ID. If staff reset while your page is
old, the server rejects the request before executing it. Refresh and inspect the
new exercise instead of repeating an old target or conclusion.

An observed new run or a changed credential clears response targets, initial
assessment and other run drafts, displayed evidence and feedback. Late replies
from the previous run/credential cannot populate the current view or announce a
successful action. The same-run ten-second polling does not erase drafts.
Cloud/recovery/feedback reads must match the inspected run; a mismatch removes
write authority and asks for a refresh. The synthetic staff directory is not a
run-specific evidence source, but late directory responses are still discarded
when the credential or run changes.

A failed state read removes write authority. A transient failure retains drafts
until a successful read confirms the same run. An unconfirmed action/submission
is never automatically repeated. Inspect current evidence/submissions with staff
before deciding whether to send a new request; a lost response can follow a
successful write. This is not an exactly-once delivery or undo guarantee.
Private help uses its existing separate run-scoped, exact-message retry workflow.

## API contract

These six authenticated participant POST endpoints accept the optional
`X-Exercise-Run-ID` header:

- `/api/participant/actions`
- `/api/participant/checkpoints/dp1`
- `/api/participant/timeline`
- `/api/participant/cloud/assessment`
- `/api/participant/recovery/action`
- `/api/participant/recovery/brief`

The scope check and operation hold the same runtime lock as reset and the clock.
It is not a check-then-release race. A stale header returns generic `409`; an
invalid or duplicate header returns `422`. Authentication, role checks, lifecycle,
allowlists, evidence provenance, dry-run and idempotency rules remain mandatory.
The timeline also retains its explicit body run ID check. Rejected stale requests
do not add actions, submissions, canonical events or fixture changes.

For compatibility, callers omitting the header keep the existing behavior and
**do not have this stale-client protection**. Integrations must copy the ID from
an authorized current state response, not infer it from a cached environment
variable. The header is a concurrency guard, not a credential or authorization
capability. This increment does not add it to the separate SSO/role-play MFA or
identity-capture service APIs. Support, evaluator judgments and archive capture
keep their existing explicit body run contracts.

## Verification and handoff

Run the application regressions from the repository root:

```sh
python -m pytest dashboard/tests/test_participant_run_safety.py -q
node --test dashboard/tests/*.test.mjs
```

The HTTP checks exercise every new guard, existing authorization/lifecycle rules,
an in-flight action racing staff stop/reset, and two full-play compositions through
all four checkpoints, recovery, terminal stop/completion, private export/archive,
reset and a fresh learner action. They use disposable files and temporary SQLite;
no listening server, external commands, VM or Splunk is involved. The separate
24-case rehearsal remains the checkpoint-combination/fault evidence suite.

Node checks execute the real client state model and participant event bindings
with DOM doubles, including all six POST paths and old-draft clearing. The new
asset is checked by deployment preflight and fingerprinted by the rehearsal
manifest. These checks are not browser visual QA or learner usability proof.

Aya owns these application changes. Anna still validates reconnect/reset wording
and the actual learner experience. Patrick verifies deployed same-origin access,
concurrency/clock behavior under range load, evidence preservation and clean VM
snapshots. [Application reset is not snapshot restoration](staff-operations.md).
Ashley coordinates rehearsal/admission/acceptance. No new service, dependency,
license or hosted deployment is introduced.
