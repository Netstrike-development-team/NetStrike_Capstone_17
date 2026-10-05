# Participant and facilitator portal API

Objective review and portable AAR exports are available at `/evaluator` for
configured evaluator/facilitator roles. Participants can submit their intrusion
timeline and load safe feedback after all five objectives are reviewed at end
of play. See [the review workflow](../docs/after-action-review.md) for roles,
offline report generation and calibration limits.

Staff can inspect local readiness and clock health directly on `/facilitator`,
and preview/capture/browse/download historical reviews on `/evaluator` without
altering current ratings. See [offline staff operations](../docs/staff-operations.md)
for guarded controls, uncertain outcomes and export-before-VM-restore limits.

This FastAPI service exposes the identity vertical slice without trusting actor, role, run, or exercise identifiers supplied by a browser.

- Participant endpoints show only participant-visible injects, accept allowlisted safe actions, and score the DP1 submission.
- Facilitator endpoints prepare, start, pause, resume, advance, manually deliver or skip an item, resolve DP2 from authoritative state, emergency-stop, reset, and inspect the full run.
- Bearer tokens and roles come from `NETSTRIKE_PORTAL_TOKENS`; there are no built-in credentials.
- SQLite persists validated events, submissions, and a queryable identity timeline. Identity capture stores only a keyed one-way reference to a submitted synthetic credential; raw passwords, cookies, MFA codes, and tokens are never written.
- Facilitators can download canonical JSONL or a flattened CSV view for evaluation and downstream ingestion.
- Interactive API documentation is disabled so participant users cannot discover facilitator routes from the service itself.
- `/participant` and `/facilitator` provide responsive, dependency-free browser consoles. Participant actions require users to enter evidence-supported target IDs; the HTML does not reveal the scenario answer identifiers.
- `/sso` provides the contained, vendor-neutral SimCorp sign-in experience. It supports deterministic failure, lockout, MFA, success, and suspicious-session views without contacting an external identity provider.

Example offline configuration:

```bash
export NETSTRIKE_PORTAL_TOKENS='{
  "replace-with-24-plus-random-characters-a": {"actor_id": "fac-01", "role": "facilitator"},
  "replace-with-24-plus-random-characters-b": {"actor_id": "learner-01", "role": "identity_responder"},
  "replace-with-24-plus-random-characters-c": {"actor_id": "simcorp-sso", "role": "identity_capture_service"},
  "replace-with-24-plus-random-characters-d": {"actor_id": "synthetic-sarah", "role": "simulated_user"}
}'
export NETSTRIKE_IDENTITY_AUDIT_KEY='replace-with-32-plus-random-bytes'
export NETSTRIKE_SSO_ALLOWED_ORIGINS='["http://ctrl01.citef.test:8080"]'
python -m uvicorn dashboard.app:create_default_app --factory --host 0.0.0.0 --port 8080
```

Tokens are injected on `CTRL01`; they must not be committed, logged, or included in exported evidence.
The audit key is also injected at runtime and must remain stable for the duration of a run.

Before startup, run `python -B -m dashboard.preflight --expect-scope identity`
under the intended environment/working directory. This validates application
inputs without creating SQLite or decoys; it does not certify runtime/range
readiness. Select the expectation matching the approved scenario, without
implicitly enabling full play. The production factory also validates before
construction. See [the deployment-input contract](../docs/application-deployment-contract.md)
for safe blockers, optional expected-scope guard and remaining owner checks.

## Profile initialization

At startup the portal validates the committed synthetic OSINT fixture. A
reviewed replacement can be provided through `NETSTRIKE_PROFILE_FIXTURE` as
a bounded local JSON file, with the seed matching the scenario configuration.
The participant console offers a role-protected, read-only staff directory
at `/api/participant/directory`; it preserves contact-confidence markers and
does not expose target bindings or attack rankings. Facilitators inspect the
profile count/catalog fingerprint in **Profile readiness**. Reset verifies the
pinned profile baseline as well as SSO/MFA state. See
[the profile input contract](../docs/synthetic-profile-contract-v1.md).

## Learner reset safety

The participant console now pins containment, DP1, timeline, cloud assessment and
recovery requests to the inspected run. Old-page requests cannot affect a newer
run when they send `X-Exercise-Run-ID`. The browser clears old drafts/targets on
observed reset, ignores obsolete responses and never automatically repeats an
unconfirmed mutation. Legacy clients omitting the optional header remain compatible
but lack this stale-client guard. See [learner run boundaries](../docs/participant-run-safety.md)
for the API list, limitations and cross-role regression checks.

## Synthetic identity capture

Only a token configured with the `identity_capture_service` role may call
`POST /api/services/identity/interactions`. The authenticated token owns the
source-service identity; a caller cannot select it in the request body. The
service accepts a bounded JSON object containing:

- `phase`, `synthetic_identity`, `action`, `result`, and `source_event_id`;
- an optional RFC 3339 `occurred_at`; and
- optional paired `credential_kind` and `synthetic_credential` fields.

The raw `synthetic_credential` exists only long enough to calculate an
HMAC-SHA256 run-scoped reference. The stored record and canonical
`identity.interaction.recorded` event contain the reference, correlation
fields, result, and provenance, but never the submitted value. Canonical events
automatically appear in the existing facilitator JSONL and CSV exports for
Splunk or after-action review. Facilitators can query the ordered current-run
timeline at `GET /api/facilitator/identity-audit`.

Reset removes the completed run's transient identity-audit projection and
verifies it is empty before reporting success. The normalized event remains in
the exercise evidence stream so it can be exported before VM snapshot restore.

## Contained SSO experience

The SSO browser and API accept requests only from exact origins listed in
`NETSTRIKE_SSO_ALLOWED_ORIGINS`. Wildcards, URL paths, embedded credentials,
and non-HTTP schemes are rejected. Use the final Cyber Range hostname and port;
do not add public origins.

Participant-facing text, the synthetic identity, deterministic initial failure
count, lockout threshold, MFA timeout, and suspicious-session descriptions are
loaded from `participant_experience.sso` in the versioned scenario definition.
The configured username must use the reserved `.test` domain. The application
does not validate against a real password: any bounded access phrase for the
one allowlisted synthetic identity advances the configured simulation. The raw
value is cleared by the browser and passed only to the issue #45 one-way audit
boundary; SQLite and exported events retain only an HMAC reference.

Every transition emits a run-correlated canonical event. Reset removes the
SSO-created session, restores MFA state, returns the browser workflow to the
sign-in view, and verifies the SSO baseline before reporting success.

## Scheduled MFA requests

The maintained exercise runtime delivers three bounded synthetic requests at
30, 90, and 150 elapsed exercise seconds, each with a 30-second deadline.
They appear on `/sso` without requiring a sign-in. Use the separate
`simulated_user` token field to approve or deny a scheduled request. This token
represents the single configured role-play identity; it cannot call participant
containment or facilitator controls. It remains in the input only, not browser
storage. Facilitators can instead use the Scheduled MFA panel in their console.

- `POST /api/sso/scheduled-mfa` requires the `simulated_user` role and an allowed origin.
- `POST /api/facilitator/mfa/decision` requires the `facilitator` role (not `technical_operator`).
- Both accept only `challenge_id` and `decision` (`approve` or `deny`). Actor,
  run, and exercise identifiers are resolved server-side.
- Paused exercise time does not consume the scheduled timeout; decisions are
  refused while paused. Stop cancels pending requests, and reset requires a
  new, unused run ID.
- Disabling Sarah, revoking the designated compromised session, removing its
  factor, or rotating the credential cancels pending requests and blocks later
  attempts. Approval never re-enables those objects or creates another session.

Local participant sign-in MFA remains separate from the scheduled role-play
request. The unauthenticated, origin-bound local endpoint cannot resolve a
scheduled challenge. SSO mutations are blocked while paused or stopped, and a
disabled account cannot approve an already-pending local sign-in challenge.

The browser polls without moving focus during background refreshes. Scheduled
timeout evidence is generated by the server even when no browser is open.
Canonical delivered/approved/denied/expired/blocked/cancelled events are retained
in SQLite and existing exports, correlated with identity/session/action audit
events. Live Splunk ingestion must still be verified in Patrick's environment.
See [the developer demonstration and evidence handoff](../docs/scheduled-mfa-dev-handoff.md).

## Human help requests

Participants can ask for help through `/api/participant/support`; staff inspect
the queue through `/api/facilitator/support` and author replies through
`/api/facilitator/support/replies`. Learners see only their own threads. Replies
are labeled hint, clarification or platform issue; no answers or grades are
generated automatically. Run IDs and retry keys prevent stale requests and
duplicate messages. Support evidence is retained in the staff AAR, review archive
and existing private event spool.

The participant console now has a private help form and thread. The facilitator
console has a human reply queue, and the evaluator page has a read-only transcript.
Technical operators can explain platform issues only. Anna retains approved hint
content, usability acceptance and evaluator calibration.
`python -m dashboard.support_demo` is an inert preview;
add `--execute` for a memory-only synthetic request/reply/archive/reset demo.
See [API use, privacy and ownership](../docs/exercise-support.md).

## Staff run-review archives

Staff review snapshots are now retained before application reset and can be
downloaded afterward using authenticated archive APIs. They remain read-only
and do not survive a VM rollback unless exported externally. See
[run-review archive usage and capture boundaries](../docs/run-review-archives.md).

## Canonical event publication

`python -m dashboard.event_spool` offers an inert preview or explicit, private
incremental JSONL publication from the SQLite ledger for a staff-only monitored
file input. It preserves old/new run evidence without changing the portal event
sink or claiming Splunk acknowledgement. Patrick owns UF/Splunk configuration
and deployment; see [usage, integrity and the handoff](../docs/event-spool.md).
An offline partial-play demonstration is available with
`python -m dashboard.event_spool_demo` (preview by default).

## Application readiness

Staff can inspect `GET /api/facilitator/readiness`. Prepare and Start now audit
and enforce local pre-play baselines, required handlers and successful setup;
Start-only clients safely prepare first. This does not certify Splunk, VM
snapshots or participant admission. See
[guarded-start usage and failure handling](../docs/application-readiness.md).

## Supervised exercise clock

The ASGI lifespan supervises the existing one-second scheduler driver. Staff can
inspect `GET /api/facilitator/clock` (also included in staff state); technical
health is not exposed in participant state. A failed tick, invalid monotonic
clock or heartbeat older than 30 seconds latches a safety stop before further
timed/interactive delivery. Shutdown drains in-flight ticks and stops active
play rather than declaring completion. Direct local CLI/service rehearsals stay
deterministic and are explicitly `unmonitored`.

Run one application process/ASGI worker per exercise, not multiple workers sharing
SQLite. A fault requires evidence preservation and successful archive/reset;
restarting a driver cannot clear the fault on the same live service/run.
See [clock health, recovery and Patrick's handoff](../docs/exercise-clock.md).

# Optional identity + mock-cloud exercise


Set `NETSTRIKE_SCENARIO_PATH=orchestrator/scenarios/cloud-slice.v1.json` and
provide a server-owned `cloud_responder` token alongside existing roles to enable
cloud investigation, preservation/remediation, assessment and staff-only DP3.
The identity-only fixture remains the default.
See [cloud handoff](../docs/mock-cloud-dev-handoff.md) for the compressed timeline
and development/acceptance boundaries.
## Opt-in full-play recovery tools

Select `NETSTRIKE_SCENARIO_PATH=orchestrator/scenarios/full-play.v1.json` and
configure the existing empty, dedicated `NETSTRIKE_IMPACT_ROOT`. Participant
recovery defaults to preview; actual restore and validation require explicit
execution with the cloud/recovery role. Staff get DP4 and one-use impact rollback.
See [impact/recovery handoff](../docs/impact-recovery-dev-handoff.md) for file
safety, reset, final brief and acceptance boundaries.

## Local evidence timeline and UI walkthrough

`/participant` links to `/evidence`, a participant-authenticated timeline of
current-run synthetic identity/endpoint/cloud/recovery signals and the caller's
own response receipts. Search/filter controls and copyable event IDs support
investigation; facilitator-only criteria and other actors' action receipts are
not exposed. This local viewer is explicitly **not Splunk**. Existing situation
updates remain messages rather than pretending each attack event is an inject.
See [the boundary and reproducible video workflow](../docs/ui-walkthrough.md).
