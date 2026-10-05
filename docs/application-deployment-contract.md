# Application deployment inputs and offline preflight

This is Aya's application-side contract, following Patrick's merged #139 offline
smoke-test work and #140 documentation index. Patrick's #101 replies record a
disconnected Ubuntu Server 26.04.1 dashboard smoke test and installer hashes. They
also explicitly retain exact bundle provenance, staged hash/licence approval,
Windows/Sysmon/Splunk ingestion, clean provisioning and restore acceptance. Those
records are progress, not evidence supplied by this new application check. See
[Patrick's smoke-test and remaining-gate reply](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/issues/101#issuecomment-5985885540).

## Check inputs before starting the service

For selected extracted-bundle source consistency, the separate
[offline release-source checker](offline-release-source-check.md) compares a saved
expected commit/inventory digest and all six source trees without runtime inputs.
Configuration preflight below remains configuration-only; neither helper verifies
an already running process, the whole installation or range acceptance.

From the matching reviewed source tree and installed existing portal dependencies,
with **the same injected environment, working directory and service identity**
intended for startup:

```sh
python -B -m dashboard.preflight --expect-scope identity
```

For an approved cloud-slice or full-play configuration, select `cloud` or
`full-play` instead. This **checks** operator intent; it does not change scenario
selection. Full play still requires `NETSTRIKE_SCENARIO_PATH` and an approved
`NETSTRIKE_IMPACT_ROOT`. The current Ansible template remains identity-only;
this PR does not change it, create VMs or select the range's release configuration.

For Patrick's existing extracted-bundle layout, run the bundled interpreter:

```sh
PYTHONPATH="$PWD/source" python/bin/python3.11 -B -m dashboard.preflight --expect-scope identity
```

Do not pass secrets as command arguments or echo the injected environment. `-B`
also prevents interpreter bytecode-cache writes. The checker does not open or
migrate SQLite, provision a marker/decoy, generate/reserve a run ID, start a
server/clock, make network calls or alter the deployment. No new package or
licence is required; it reuses the existing application validators/dependencies.
Missing dependencies produce a safe `inspection_unavailable` blocker.

- Exit `0`: inputs passed the **configuration-only** checks.
- Exit `1`: one or more safe check IDs blocked inspection/configuration.
- Exit `2`: invalid CLI arguments, without echoing accidentally pasted values.

Output contains check IDs/statuses, fixed warnings, selected scope and known role
names—not bearer values/hashes, audit keys, actor IDs, origins, private file paths,
profile prose or raw parser exceptions. Do not treat `configuration_valid=true`
as `ready_to_start`, live source ingestion or participant-admission permission.

## Environment contract

| Variable | Application behavior |
| --- | --- |
| `NETSTRIKE_PORTAL_TOKENS` | Required JSON object of opaque tokens to exactly `actor_id`/`role`. At least 24 and at most 4096 characters per token, no whitespace/control characters; bounded exercise actor IDs, recognized portal roles. Duplicate keys/fields and non-string/coerced principals are refused. |
| `NETSTRIKE_IDENTITY_AUDIT_KEY` | Required UTF-8 secret, at least 32 bytes; never included in reports. |
| `NETSTRIKE_SSO_ALLOWED_ORIGINS` | Required nonempty JSON array of exact HTTP(S) origins; existing allowlist rejects wildcard/userinfo/path/query configurations. |
| `NETSTRIKE_PORTAL_DATABASE` | Defaults to `output/netstrike-portal.sqlite3`, relative to the process working directory. Only path shape/current regular-file target and existing ancestors are inspected; SQLite content and write permissions are **not** tested. `:memory:` remains supported with an ephemeral-storage warning. |
| `NETSTRIKE_RUN_ID` | Optional bounded exercise identifier. Omission preserves startup UUID generation. Full-play directory IDs must satisfy the existing stricter impact contract; an already-present fixture is not adopted. |
| `NETSTRIKE_SCENARIO_PATH` | Defaults to identity slice. Selected local scenario JSON is bounded to 1 MiB and duplicate fields are rejected by configuration inspection; existing definition validation applies. |
| `NETSTRIKE_PROFILE_FIXTURE` | Defaults to reviewed local profile fixture. Existing roster/schema/seed/SSO/MFA/witness bindings are validated without creating a runtime. |
| `NETSTRIKE_IMPACT_ROOT` | Required for selected full play; existing absolute dedicated root ownership/structure checked without writing its marker or files. Ignored as an impact prerequisite for identity/cloud slices. |
| `NETSTRIKE_EXPECTED_SCENARIO_SCOPE` | Optional `identity`, `cloud` or `full-play` expectation, also enforced by production factory. A CLI expectation cannot weaken a conflicting configured expectation. This guard does not enable a stage. |

Input validation now runs **before** `create_default_app` constructs the store and
runtime. It uses the validated authenticator/origins rather than reparsing secrets
after provisioning. Known invalid inputs therefore cannot leave a newly created
SQLite database or full-play fixture behind. Successful startup still intentionally
creates/migrates its database and, for explicitly selected full play, provisions
five disposable decoys. If later runtime/app construction fails, the constructed
store is closed; evidence/partial files are preserved, never automatically deleted.

Preflight does not reserve a run, pin files, establish a lock/lease or guarantee
future construction succeeds. Startup validates again; use an immutable reviewed
release and do not change inputs while starting. Permissions, input replacement,
actual persistence or a later adapter failure can still fail after construction
begins. Never infer crash-resume from a retained SQLite database: existing runtime
readiness rejects a reused event ledger; a fresh run/snapshot procedure is required.

## Unverified prerequisites and role warnings

The JSON explicitly keeps `runtime_readiness_verified=false` and
`external_readiness_verified=false`. It does **not** verify:

- Database integrity/history, prior-run collisions or real write permissions.
- Runtime action handlers/baselines or supervised-clock delivery under load.
- TLS key traversal/readability, certificate trust, service account or worker count.
- VM allocation/targets, DNS/NTP, network isolation or reachability.
- UF/Sysmon installer bytes/licences, bundle revision/digest/lock or exact architecture.
- Splunk ingestion/index/retention, staff/participant access or daily volume.
- Snapshots, evidence outside reverted VMs or facilitator admission/client approval.

Role gaps are warnings, not fabricated credentials or a silently selected role.
For example, no facilitator/technical-operator credential means controls cannot be
used; no facilitator/evaluator credential means no review access; full play without
a cloud responder has no learner cloud/recovery write credential. It remains the
operator's responsibility to configure the exercise audience and staff accounts.

After startup, use authenticated [application readiness](application-readiness.md),
[clock inspection](exercise-clock.md) and [staff operations](staff-operations.md).
Then complete Patrick's independent environment checks and human admission gates.
Deploy **one process/one ASGI worker per runtime**; preflight warns but does not
inspect or enforce Uvicorn command-line worker settings, TLS or systemd hardening.

## Owner handoff and verification

Aya owns configuration/factory behavior and defects evidenced by these checks.
Patrick continues to own bundle provenance/licences, actual service/TLS access,
Ansible/Splunk/Windows installation, data-health and live clean-snapshot rehearsals.
Anna owns final wording/usability/calibration; Ashley coordinates release decisions.
No changes to Patrick's playbooks, installer inventory or bundle builder are needed
to include this helper: it lives in the already-bundled `dashboard/` source tree.

Tests execute safe CLI failures (including missing dependencies), valid/mismatched
scope, immutable input inspection, full-play no-write failures, real in-memory
factory start/stop/reset, and store cleanup on construction failures. Existing
profile/MFA/impact validators are shared, not independently reimplemented scenario
rules. Full-play regression evidence fingerprints the new helper/configuration.
These remain local developer tests, not an additional recorded Cyber Range run.
