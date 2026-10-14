# Scheduled synthetic MFA — developer demo and handoff (#29)

## Delivered development scope

Three local requests are attached to the existing identity MSEL at 00:30,
01:30, and 02:30 elapsed exercise time. Each expires after 30 exercise seconds.
There is no push service, device/phone/tenant integration, credential validation,
real MFA code, automatic approval threshold, or unlimited request loop.
This is an observable role-play sequence in the Python mock identity provider.
It does not replace the staged pre-exercise compromise history or expand the
blue-team exercise duration, objectives, or topology.

## Quick browser demo

Use the existing dashboard startup configuration in `dashboard/README.md`.
Inject distinct randomly generated facilitator, identity-responder, and
simulated-user tokens; configure the exact local exercise origin. Never use
production accounts or put real token values in screenshots, recordings, or Git.

1. Open `/facilitator`, connect with the facilitator token, Prepare, then Start.
2. Open `/sso` in a separate participant window. Enter only the simulated-user
   token in its exercise-control field. Do not show the facilitator console to
   learners during the actual exercise.
3. Advance to **30** from the facilitator console. The first request appears
   on `/sso` without a sign-in. Select **Deny**; the outcome and audit event
   are visible. The facilitator can also choose approve/deny as Sarah.
4. Advance to **90**. Leave the second request pending. Pause and show that
   the deadline freezes and decisions are disabled/refused. Resume, advance
   to **120**, and show the expired outcome.
5. Advance to **150**, then use the identity-responder participant console
   to revoke session `sess-red-01` (or disable identity `sarah`). The pending
   request is cancelled with the corresponding containment reason.
6. Download the current JSONL from the facilitator console. Emergency-stop,
   reset to a new run ID, and verify the SSO request history and identity state
   are clean. Old challenge IDs cannot decide requests in the new run.

To demonstrate approval, use a separate run and approve the first request.
This records a successful **synthetic MFA decision**, not a signed-in browser
session and not a newly minted attacker token. The designated compromised
session already exists in the staged baseline. Approval never overrides
containment. For future-attempt blocking, revoke the session after the first
request, then advance to 90/150 and inspect the blocked outcomes.

## Evidence contract

All scheduled records have `source.component=scheduled-mfa`, `phase=identity`,
and the existing canonical v1 envelope. `target.id=sarah`; shared correlation
IDs identify the challenge and `sess-red-01`. `data` includes `challenge_id`,
`msel_id`, `identity_id`, `session_id`, `factor_id`, `elapsed_seconds`, delivery
and expiry instants, and a bounded reason. Human actor/role comes from the
authenticated principal, not JSON supplied by a browser.

| Event suffix | Meaning | Evidence reason |
| --- | --- | --- |
| `delivered` | Local request awaits a person | `awaiting_human_decision` |
| `approved` / `denied` | Explicit human choice | `human_decision` |
| `expired` | No choice before the exercise deadline | `exercise_timeout` |
| `cancelled` | Pending request invalidated | containment reason or `fail_safe_stop` |
| `blocked` | Later scheduled attempt cannot deliver | containment reason |

Event names are `identity.mfa.challenge.<suffix>`. Containment reasons are
`account_disabled`, `session_revoked`, `factor_removed`, and `credential_rotated`.
Existing safe-action audit events remain in the same exercise/run sequencer;
their target IDs join to the MFA fields. DP2 remains the objective containment
verifier. A facilitator's approval choice does not automatically penalize the
blue team; the team's detection, investigation, and containment evidence does.

The same seed, schedule, and human inputs give the same logical outcome
sequence. Tests compare tick-by-tick execution with a single time jump.
Different runs intentionally have different challenge IDs, event UUIDs, and
wall-clock timestamps. Use `data.elapsed_seconds` for exercise time, and
`sequence` for authoritative audit order; a time jump can emit multiple
wall-clock events together.

## Patrick's environment verification (not claimed complete)

Use the **canonical JSONL**, not CSV, to preserve the nested correlation fields.
This PR provides valid events/exports, not an automatic live Splunk transport.
The dedicated index, ingestion path, timestamp/JSON extraction configuration,
permissions, and forwarder/HEC automation remain Patrick's scope (#102).

Replay a demo export into the approved offline Splunk environment and verify:

- all delivered/denied/approved/expired outcomes appear under the correct run;
- containment audit records and cancelled/blocked MFA records join on Sarah,
  the designated session, or factor IDs;
- actor/role attribution is present for decisions, without any credential/token;
- participant access does not expose facilitator-only controller events;
- reset creates a distinct run without mixing prior challenge state/evidence.

Anna can rehearse the simulated-user decision experience using the browser
steps; her participant wording/storyline and evaluator materials remain her
scope. Ashley can coordinate the live environment/rehearsal verification.

## Verified locally

Run the focused regression suite from the repository root:

```bash
pytest shared/tests orchestrator/tests dashboard/tests \
  modules/04-mfa-fatigue-sim/tests \
  modules/05-lateral-movement/tests/test_endpoint_actions.py -q
node --check dashboard/static/sso.js
node --input-type=module --check < dashboard/static/facilitator.js
```

Coverage includes explicit role-bound choices, exactly-once pending resolution,
deterministic time jumps, expiry with no browser, pause/resume, containment,
stop/reset and stale-request rejection, origin/payload boundaries, and canonical
SQLite/JSONL export. Browser visual rehearsal and live Splunk acceptance are
separate checks; automated API/static checks are not evidence of either.

The broader local regression also includes the complete endpoint/AD tests:
`pytest shared/tests orchestrator/tests dashboard/tests modules/04-mfa-fatigue-sim/tests modules/05-lateral-movement/tests -q`.
