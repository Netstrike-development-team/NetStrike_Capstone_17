# Full-play deployment runbook

Use this runbook to deploy or reprovision the full exercise. Detailed
configuration, artifact, readiness, safety, and Splunk procedures are linked
below rather than repeated here.

## Before provisioning

1. Build and verify the [offline bundle](offline-bundle.md).
2. Prepare the actual target manifest, licensed-installers archive, and private
   secrets file as described in the [CITEF provisioning guide](../citef-config/README.md).
   Confirm the required TLS material and credentials are available through the
   approved secret process; do not commit secrets or put them in command
   arguments or logs.
3. Use a fresh, access-restricted work directory. The wrapper copies the secrets
   file into its extracted bundle.

## Provision

From the repository root on `ANSIBLE01`, run the wrapper with the six required
inputs in order: application bundle, licensed-installers archive, environment
manifest, secrets file, deployment version, and unique exercise run ID. The
optional seventh input is the work directory. If the wrapper was downloaded
separately, run `./provision.sh` instead of `./scripts/provision.sh`.

```sh
umask 077
./scripts/provision.sh \
  netstrike-CTRL01-BUNDLE_BUILD.tar.gz \
  licensed-installers.tar.gz \
  environment.json \
  secrets.yml \
  REVIEWED_RELEASE \
  UNIQUE_EXERCISE_RUN_ID \
  ./offline-bundle-initial
```

Replace every example value with the reviewed deployment input. The sixth
argument is the shared `exercise_run_id`—not the bundle build ID—and is passed
to the portal and project-configured host forwarders. The wrapper selects
full-play by default; it has no scope argument.

The wrapper verifies and stages the bundle, validates the environment, and runs
`provision.yml` with its provisioning validation. `SPLUNK01` is range-managed
and is not configured by this project.

## Verify and admit

Provisioning is not readiness or acceptance. After it completes:

1. Confirm the portal and configured host forwarders use the intended run ID.
   This is configured intent; it does not prove that forwarders loaded the
   configuration or that events reached Splunk.
2. Run the separate `readiness.yml` playbook and inspect the portal's
   authenticated application-readiness report.
3. Verify live application and host telemetry in Splunk for the same run ID,
   including source freshness, gaps/duplicates, and participant/staff access.
4. Complete the deployed-environment and facilitator admission checks before
   starting the exercise.

Use the [safety and reset procedure](exercise-design/04-safety-and-reset.md)
for environment, snapshot, readiness, and admission checks; the
[Splunk/Sysmon ingestion guide](splunk-sysmon-ingest.md) and
[learner telemetry handoff](learner-splunk-audit.md) for live-source checks.
The provisioning wrapper does not run `readiness.yml`, restore snapshots,
configure Splunk, or authorize participant admission.

## Next exercise

Preserve evidence outside any VM that will be reverted, restore the clean
pre-provision snapshots, then repeat provisioning with a **new unique run ID**
and a fresh restricted work directory. Do not reuse the previous ID, rerun
against retained application state instead of restoring, or remove portal state
to force a restart. An application-only reset creates a new portal run but does
not update host forwarders; do not bypass the resulting run-binding mismatch.
Follow the [safety and reset procedure](exercise-design/04-safety-and-reset.md)
and repeat the verification and admission steps above.
