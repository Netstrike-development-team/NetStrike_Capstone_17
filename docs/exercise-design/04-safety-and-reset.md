# Safety and Reset Requirements

## Safety objective

Operation Silent Spider must create useful evidence and response decisions without creating a path to harm real users, systems, data, or Cyber Range control infrastructure.

## Mandatory safety controls

### Environment isolation

- Run only inside a Cyber Range-approved isolated exercise network.
- Deny Internet egress by default. Any package mirror or management access is configured separately by the Cyber Range.
- Maintain an explicit allowlist of target host IDs, addresses, accounts, service names, and writable directories.
- Refuse to start when the resolved targets do not match the approved environment manifest.
- Keep `CTRL01`, `SPLUNK01`, the hypervisor, and snapshot controls outside participant and attack-module administration.

### Identities and data

- Use only fictitious SimCorp identities and exercise-specific credentials.
- Use reserved or private exercise addresses; never insert a real third-party address as an attacker target.
- Do not store real passwords, MFA secrets, tokens, phone numbers, or personal information.
- The fake SSO interface must be branding-neutral, display an exercise-use banner in source/configuration, and reject requests from outside the lab.
- Cloud and customer records must be synthetic and clearly marked as such.
- Secrets must be injected at runtime and excluded from version control, logs, screenshots, and reports.

### Action controls

- Every automated action requires a registered action ID, timeout, allowed targets, expected effects, rollback method, and dry-run test.
- The scenario engine may invoke only actions referenced by the approved MSEL.
- Re-running an action must be safe or must fail closed with an understandable status.
- Modules must not install packages at import or execution time.
- Remote actions should run with the least privilege needed for the single action.
- Rate-limit MFA, authentication, API, and file operations.
- A module failure must not automatically advance to a more impactful action.

### Impact simulation

- Marker mode is the only supported MVP mode.
- Do not encrypt files, VM disks, backups, or snapshots.
- The only writable target is the run-specific disposable directory approved in the environment manifest.
- The adverse branch may move disposable originals to a controller-managed staging directory to simulate unavailability; it must not overwrite them.
- Calculate a manifest and hashes before and after the stage.
- Never connect the MVP impact module to a real vCenter API.

### Logging and privacy

- Record controller actions, branches, participant changes, retries, fallbacks, and errors with `run_id` and UTC timestamps.
- Redact configured secret fields before logging or exporting an AAR.
- Separate participant-visible telemetry from facilitator-only ground truth.
- Retain exercise results according to a Cyber Range-approved period; do not silently delete evidence after a run.

## Emergency stop

The facilitator and technical operator must have an authenticated emergency-stop control that:

1. prevents the scenario engine from scheduling new actions;
2. cancels or terminates currently running registered actions where supported;
3. disables exercise attacker accounts and mock-cloud keys;
4. blocks the designated simulated remote-access path;
5. records the reason, operator, time, running action, and result; and
6. leaves evidence intact for troubleshooting.

An emergency stop is mandatory for target mismatch, unexpected external connectivity, modification outside the allowlist, loss of controller visibility, unsafe participant behavior, or an uncontained automated process.

## Baseline manifest

Each exercise instance must have a versioned baseline manifest containing:

- scenario and software version;
- VM/logical asset mapping;
- expected host identifiers and addresses;
- required services and health endpoints;
- baseline users, factors, sessions, groups, and permissions;
- mock-cloud principals, key states, buckets, objects, and approved policy hashes;
- disposable file names and SHA-256 hashes;
- snapshot or image identifiers;
- allowed action targets and directories; and
- required Splunk data sources.

## Reset procedure

The target reset time is 20 minutes or less.

### 1. Close and archive the run

- Stop the scenario through the controller.
- Mark all MSEL items final: completed, failed, skipped, fallback, or cancelled.
- Export the run ledger, participant submissions, evaluator observations, score, and technical errors.
- Preserve the branch-specific evidence bundle used during the run.

### 2. Stop exercise activity

- Confirm no registered attack action, remote task, MFA burst, directory query, mock-cloud request, or impact task remains active.
- Disable all run-specific attacker sessions, factors, accounts, and keys.
- Remove temporary network isolation overrides created by participants.

### 3. Restore infrastructure

Use the Cyber Range-approved snapshot restore when available. Ansible then applies configuration validation and any required idempotent baseline corrections. If snapshots are unavailable, the complete state reset must explicitly:

- reset SimCorp identity passwords, factors, and sessions;
- remove `svc-print-sync` and restore group memberships;
- restore endpoint connectivity, approved processes, and configuration;
- rebuild mock-cloud principals, keys, buckets, objects, and policy;
- restore disposable files from the known-good copy and remove marker/ransom artifacts;
- clear run-specific portal tickets and submissions from the active view; and
- create a new `run_id` without altering the archived prior run.

### 4. Handle Splunk data

- Do not require destructive index deletion for every reset.
- Isolate runs using `run_id`, exercise time, or a Cyber Range-approved per-run index.
- Confirm the new run cannot see answer-revealing facilitator/internal events.
- Confirm all required sources are reporting fresh health events.

### 5. Validate readiness

The automated readiness check must fail unless:

- all logical assets resolve to approved targets;
- required services respond;
- baseline identities, groups, factors, sessions, keys, policies, and files match the manifest;
- no prior run action remains active;
- disposable file hashes match;
- the event ledger accepts the new `run_id`;
- Splunk receives a test event from every required source; and
- emergency stop is reachable by exercise staff.

The facilitator signs the readiness record before admitting participants.

## Dry-run requirements

Before release:

- run every individual action twice against a disposable baseline;
- intentionally fail each external dependency and verify that the exercise pauses safely;
- test both outcomes at every decision point;
- confirm all expected telemetry using the evidence matrix;
- execute a full reset after each branch combination selected for testing;
- conduct at least three end-to-end runs, including one with someone who did not author the software; and
- conduct at least one full run on CITEF.
