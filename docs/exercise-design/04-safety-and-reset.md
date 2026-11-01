# Safety and Reset Requirements

## Safety objective

Operation Silent Spider must create useful evidence and response decisions without creating a path to harm real users, systems, data, or Cyber Range control infrastructure.

## Mandatory safety controls

### Environment isolation

- Run only inside the isolated exercise network selected and configured by the team under delegated Cyber Range authority; further range allocation approval is not required.
- Keep delivery independent of Internet access. Patrick accepts the October 21 DNS-blocking setup as sufficient #79 isolation evidence. That acceptance does not claim every direct-IP or other egress path is blocked; unexpected external connectivity still requires emergency stop. The team controls exercise network and management configuration.
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

## Snapshot restoration and readiness procedure

Capture the clean snapshots after the OS is installed and each target's remote
management path (SSH/WinRM) is enabled, but before running the Ansible
playbook. This preserves a usable management path while keeping exercise
baseline and telemetry changes out of the clean starting point; snapshots do
not wait for baseline or telemetry checks. There is no custom 20-minute reset
target.

The Cyber Range operator performs hypervisor snapshot restoration. Patrick
coordinates snapshot preparation and the restore/readiness workflow; Zian and
Julien are the escalation contacts for an unavailable or failed restore. The
student team owns topology and validation. Ansible reapplies configuration and
runs automated readiness checks; it does not reconstruct every VM after each
delivery. A failed readiness result blocks participant admission.

VM allocation, images, sizing, addresses, DNS/NTP, firewall rules, and access paths
are already delegated to the team. Validate deployed controls against the team's
manifest, not against an outstanding range permission request. Zian/Julien
remain assistance and escalation contacts; final exercise sign-off is separate.

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

Restore every scenario VM from its clean snapshot. Ansible then configures the
environment and performs the documented readiness checks. If a snapshot fails
or is unavailable, stop the next delivery and escalate to Zian/Julien rather
than attempting an unapproved partial reset.

The current Ansible provisioning/readiness workflow checks configured inventory
host identity and architecture, DNS, clock state, required services, the
configured AD domain and users' enabled state/group memberships, local
application readiness, and run-correlated Splunk probes. It does not reset or
verify all of the broader exercise state below, including sessions/factors,
mock-cloud state, disposable-file hashes, active actions, or emergency-stop
reachability. Those remain separate implementation and acceptance checks; do
not treat a passing Ansible play as proof of them.

### 4. Handle Splunk data

- Do not require destructive index deletion for every reset.
- Isolate runs using `run_id`, exercise time, or a Cyber Range-approved per-run index.
- Confirm the new run cannot see answer-revealing facilitator/internal events.
- Confirm all required sources are reporting fresh health events.

### 5. Validate readiness

Run the Ansible `readiness.yml` playbook and verify that portal startup passes
its local preflight/readiness gate. A failed readiness check must block
participant admission; use the actionable blocker evidence in the playbook or
portal logs to diagnose and escalate. Current automated checks cover inventory
host identity, OS family, DNS, clocks, required services, the configured
portion of the AD user baseline, local application readiness, and configured
run-correlated Splunk probes. Full delivery acceptance must also verify the
following independently; the current playbooks do not establish all of them:

- deployed targets and network/access controls matching the team-selected manifest (allocation authority is established and October 21 DNS blocking is accepted #79 isolation evidence);
- identity/session/factor state, mock-cloud keys and policies, and disposable-file hashes;
- no prior run action remains active and the new run ID preserves prior evidence;
- live forwarder configuration, all-source freshness, and participant/facilitator Splunk access; and
- emergency stop is reachable by exercise staff and behaves as required.

The facilitator signs the readiness record before admitting participants.
The October 21 local rehearsal passed restore/reprovision/readiness three times,
but not consecutively, and used Docker-hosted Splunk rather than a range-managed
Splunk VM. It therefore does not meet the consecutive-cycle acceptance
criterion. Reuse its provisioning and telemetry evidence. Local readiness is
not itself an admission certificate; staff must separately verify deployed
access controls and emergency-stop reachability. See the
[baseline screenshot checklist](../offline-bundle-provisioning-validation.md#baseline-evidence-to-capture).

## Dry-run requirements

Before release:

- run every individual action twice against a disposable baseline;
- intentionally fail each external dependency and verify that the exercise pauses safely;
- test both outcomes at every decision point;
- confirm all expected telemetry using the evidence matrix;
- restore the clean snapshots and pass readiness after each branch combination selected for testing;
- conduct at least three end-to-end runs, including one with someone who did not author the software; and
- conduct at least one full run on CITEF.
