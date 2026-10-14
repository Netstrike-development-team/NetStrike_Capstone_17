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

## Pending submissions and inspection (#163)

All six learner mutation paths share one pending-request lock. It survives
observed account/run changes until that server request settles: switching tokens,
refreshing, or resetting does not permit a second concurrent action from this
page. Mutation buttons start disabled in HTML, enable only after a valid current
state inspection, and stay disabled while a write or post-write inspection is
pending. State/clock metadata are not shown as connected authority while inspection
is required. Server roles, targets and lifecycle checks remain authoritative.

Starting a write immediately invalidates prior state/evidence callbacks, not
just after its response arrives. Reads begun during a write cannot grant action
authority after it settles. For overlapping cloud, recovery, feedback or directory
reads, only the latest request to that endpoint can update the view; obsolete
successes and failures are discarded. A valid global state read is not a promise
that previously displayed cloud/recovery facts are fresh—use their evidence
refresh controls to inspect the specific outcome.

After a write settles the console performs only a new state GET, never a replayed
POST. Healthy same-run inspection preserves drafts and target inputs. An
unconfirmed write or failed post-write inspection keeps actions unavailable until
inspection succeeds. A confirmed action receipt is not proof of containment or
of successfully refreshing every evidence panel. Explicit Connect/reconnect
starts a new observed credential generation, including same-token reconnect.
Observed account/run changes clear old drafts and evidence. Unobserved transient
token changes, other tabs and direct API clients are outside the page-local lock;
this is not backend exactly-once delivery or server cancellation.

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
capability. The SSO/role-play APIs separately gained the same guard in #162; see
[SSO run safety](ui-walkthrough.md#synthetic-sign-in-and-mfa-run-safety-161).
The identity-capture service is separate. Support, evaluator judgments and archive capture
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
The #163 regression first reproduced two cloud-assessment POSTs while one was
pending (expected one). Additional checks cover overlapping state/evidence
requests, credential A→B→A, new-run pending locks, malformed metadata,
post-write inspection, drafts, disabled markup and render failures. Participant
HTML/JS/state model already participate in exact rehearsal source fingerprints.

Aya owns these application changes. Anna still validates reconnect/reset wording
and the actual learner experience. Patrick verifies deployed same-origin access,
concurrency/clock behavior under range load, evidence preservation and clean VM
snapshots. [Application reset is not snapshot restoration](staff-operations.md).
Include rapid double submit/across-form actions, a slow write across reconnect
and reset, failed post-write inspection and delayed cloud/recovery reads on the
actual final deployment in #99/#104. Their acceptance issues remain open.
Ashley coordinates rehearsal/admission/acceptance. No new service, dependency,
license or hosted deployment is introduced.
