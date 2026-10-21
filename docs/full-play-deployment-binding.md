# Full-play deployment and configured host-run binding

Aya-owned application integration following Patrick's #178–180. This connects
the deployment inputs to existing application behavior; it does not configure
live VMs, certify ingestion or change range admission rules.

## Initial deployment

The controller role defaults `controller_scenario_scope` to `full-play`. The
allowlist maps `identity`, `cloud` and `full-play` to the corresponding reviewed
scenario file. An explicit scoped test can override it, for example:

```sh
ansible-playbook -i inventory.ini playbooks/provision.yml -e @secrets.yml \
  -e deployment_version=REVIEWED_RELEASE \
  -e exercise_run_id=UNIQUE_EXERCISE_RUN \
  -e controller_scenario_scope=identity
```

Omit the last option for the full exercise. Use approved manifests and actual
targets, never guessed/example addresses. Existing deployment prerequisites,
license approval, secrets, network isolation and human admission remain required.
`scripts/provision.sh` retains its existing argument positions and selects the
full exercise through the role default; use the direct playbook for a scoped
override.

The actual startup environment supplies:

- `NETSTRIKE_SCENARIO_PATH`: the selected allowlisted file.
- `NETSTRIKE_EXPECTED_SCENARIO_SCOPE`: the matching scope, independently checked
  by the production factory and systemd's read-only preflight.
- `NETSTRIKE_RUN_ID`: the same `exercise_run_id` supplied to all host forwarders.
- `NETSTRIKE_HOST_TELEMETRY_RUN_ID`: a local configured binding to that same ID.

The existing `/var/lib/netstrike/fixtures` is the dedicated disposable root.
Preflight inspects it without creating a marker, decoy or database. Full-play
startup provisions only the existing five allowlisted decoys; unexpected files,
an unsafe root or reused run fixture still fail closed. No fixture is adopted,
cleared or overwritten to make startup pass. An already-running process is not
verified by preflight, and restarting a retained run is not crash-resume.

Ansible flushes pending portal changes before its ensure-started task, so the
initial deployment does not start and immediately restart the same run. The
handler reloads systemd before starting the new unit; source/dependency changes
also request that handler. The unit pins one Uvicorn worker and disables automatic
restart. Preserve state and use the restore/new-run procedure after process
failure or when replacing an already-used deployment; these changes do not add
crash-resume. The event spool timer starts only after authenticated local
readiness confirms the configured run and baseline.

## Reset and next-run admission

The binding is optional for standalone local applications but always supplied
by this deployment template. If present, configuration validation requires an
explicit matching portal run ID before opening the store or creating fixtures.
It is **configured intent**, not proof of any forwarder's actual loaded config
or of events arriving at Splunk.

Application reset still archives the previous review, retains its ledger and
restores the decoys. It creates a fresh run ID; it does not reach into Windows,
rewrite forwarder configuration, relabel old logs or contact Splunk. A fresh ID
that differs from the configured host binding therefore blocks both Prepare and
Start with `configured_host_telemetry_run`. Staff readiness and stop/reset access
remain available. Do not disable the binding to admit a deployed exercise.

For the next deployed exercise:

1. Export/preserve staff evidence outside the VMs that will be reverted.
2. Coordinate the approved clean-snapshot restoration with Patrick/range staff.
3. Provision the clean environment and **every forwarder** with one new shared
   `exercise_run_id`. Do not reuse the previous ID or remove a database/fixture
   manually to force restart. The exporter retains its ordinary prefix-integrity
   protections; reverted databases and old spools must not be mixed.
4. Confirm the portal reports that ID, then use Patrick's searches to prove live
   application and host events for that same ID. Check source freshness,
   duplicates/gaps, access separation, clocks and saved raw-export reconciliation.
5. Complete the separate environment and human admission checks before Start.

The local check does not automatically restore snapshots, rebind hosts or
acknowledge external readiness. Standalone demos that omit the binding keep
their existing reset/restart-in-place behavior.

## Developer evidence and remaining ownership

Regressions render the actual Jinja startup template with synthetic credentials,
relocate only VM paths into test-owned directories and use the real production
factory and API. They cover default full play, scoped identity/cloud overrides,
same-ID startup, mismatched/missing ID rejection before writes, stop/reset,
evidence retention, stale-binding admission refusal and unbound local replay.
The role selector, systemd preflight and source provenance are also checked.
Jinja2 is a developer-test dependency already used by Ansible, not a new portal
runtime dependency. CI runs these and the static Splunk configuration tests.

These are automated local tests, not learner/range acceptance. Patrick retains
live Splunk/forwarder, Windows/AD, TLS, network, clean provisioning and snapshot
validation. In particular the existing disabled AD plays and relaxed local-test
infrastructure checks are **not fixed or approved by this change**. Anna owns
participant wording/usability and calibration; Ashley coordinates acceptance.
