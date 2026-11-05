# NetStrike Splunk content (#102)

Versioned, secret-free Splunk Enterprise 10.0.1 content. Patrick's closed #102
records October 16 live source-health, participant-separation, volume and
fresh-redeploy checks; #103 records October 21 three-host run-tagged ingestion
screenshots. Reuse those records for their tested scope. A saved-file checker or
static test still leaves `splunk_ingestion_verified` false and does not certify
a later deployment or complete range rehearsal.

| Path | Deploy to | Purpose |
|---|---|---|
| `staff/netstrike_staff` | Splunk server (`$SPLUNK_HOME/etc/apps`) | Indexes, roles, parsing, data-health, access checks, run probes, DP1 solution-guide searches. Facilitator-only. |
| `participant/netstrike_participant` | Splunk server | Neutral investigation searches over `netstrike` only. No staff index, answers or checkpoint logic. |
| `forwarder/netstrike_app_events_inputs` | CTRL01 Universal Forwarder (`splunkfwd`) | Monitored-file input for committed `batch-*/events.jsonl` spool batches (#130). |

Windows Security/PowerShell/Sysmon and Linux inputs already come from
`citef-config/roles/*_telemetry`; they are not duplicated here.

## Design decisions

- **Two indexes.** `netstrike` (CITEF-approved, participant-searchable) holds host
  telemetry and the separate reviewed SimCorp audit projection. The canonical application ledger contains facilitator/evaluator events
  and answer labels, so it goes to **`netstrike_staff`**, which only
  `netstrike_facilitator` can search. A visibility field is not access control, so
  no `srchFilter` is relied on. **Index creation is already delegated to the team
  and covers `netstrike_staff`, as Patrick confirmed in the October 16 #102 update.
  No further range index-creation approval is required.**
- **Retention** is the approved one day (`frozenTimePeriodInSecs = 86400`, hot
  buckets capped at a day). Splunk freezes whole buckets, so expect data to persist
  slightly longer. Events with timestamps older than a day (backdated PRE-02 history)
  may be frozen almost immediately.
- **Roles.** `netstrike_participant` imports nothing. Do not also give participants
  the built-in `user` role: Splunk unions role permissions, so `user` exposes
  `netstrike_staff` (verified live). `netstrike_facilitator` imports `power`. Assign
  real users to them; none exist in the repo.
- **Participant application events.** A separate fact-only projection uses
  `netstrike:learner:audit:v1`; neutral timeline/identity/helpdesk/storage searches
  are included. See [contract and live handoff](../docs/learner-splunk-audit.md).
  This is simulated application evidence, not vendor/Windows logs or a new EDR.
- **Parsing.** JSON is extracted on the forwarder (`INDEXED_EXTRACTIONS=json`,
  `timestamp` as event time) because sorted keys make a regex time prefix unsafe.
  `crcSalt=<SOURCE>` keeps similar immutable batches distinct; renaming the spool
  path re-indexes it.
- **Run ID.** Application events carry `run_id` in the JSON body. Host sources get it
  from the forwarder `_meta = run_id::{{ exercise_run_id }}` in each `inputs.conf.j2`
  stanza (an indexed field; `fields.conf` declares it). Search `run_id=<id>`, not the
  bare string. `exercise_run_id` is the unique exercise-run ID and must be identical on
  all hosts; `deployment_version` is the deployed dashboard version (controller
  release path only). `scripts/provision.sh` requires both. `run_id` is not a default
  "selected field"; tick it under All fields or use a saved search with `table`.
- **Portal binding.** The controller template now passes the same run ID to the
  application and defaults to full play. A portal-only reset does not update the
  forwarders, so its stale local binding blocks the next Prepare/Start. Use the
  [clean-deployment handoff](../docs/full-play-deployment-guide.md); this local
  guard is not a substitute for the live per-source probe or #158 reconciliation.
- **Windows fields** use `rex` on rendered XML (no add-on assumed).
- **Checkpoint 1 = DP1** (identity triage: Sarah, ≥3 artifacts from ≥2 sources,
  per `orchestrator/checkpoints.py`).
- **Licence** limit is 10 GB/day (CITEF record, 2026-10-02); the volume alert fires at 80%.

## Distinguish scenario health from participant evidence

Facilitators should use index and sourcetype to select the evidence contract,
then inspect event type and context within the private audit. A source component
name alone is not a health/evidence classification: a simulator can emit both
setup/control records and learner-observable facts.

| Data | Search scope | Interpretation |
| --- | --- | --- |
| Private application audit | `index=netstrike_staff sourcetype="netstrike:event:v1"` | Complete canonical ledger, including readiness, scenario control, checkpoints, judgments, archives and originals of projected learner facts; not every row is a health event |
| Participant application evidence | `index=netstrike sourcetype="netstrike:learner:audit:v1"` | Reviewed, allowlisted synthetic SimCorp service facts |
| Participant host evidence | `index=netstrike` with Windows/Linux sources | Actual host telemetry, separate from synthetic application facts |

For participant application evidence, replace the sample run ID and select a
time window covering that run:

```spl
index=netstrike sourcetype="netstrike:learner:audit:v1"
run_id="YOUR_RUN_ID"
```

For facilitator inspection of the private application audit:

```spl
index=netstrike_staff sourcetype="netstrike:event:v1"
run_id="YOUR_RUN_ID"
| table _time event_id source.component event_type visibility
```

The **Source overview** report spans application and host telemetry.
`OK` means a source is sufficiently recent, not that a learner performed an
objective correctly. `IDLE`/`STALE` describe freshness; the lookup's `required`
flag controls health-alert behavior, not participant visibility or grading.

Participants must remain restricted to `netstrike`. A canonical event's
`visibility=participant` is not permission to expose the private ledger:
projection requires the reviewed event type, producer and visibility to match.
See [the separate evidence contracts](../docs/learner-splunk-audit.md#separate-evidence-contracts)
for allowed facts and exclusions.

## Deploy

1. Splunk server: copy the `staff` and `participant` apps, restart, create users and
   assign roles. Store credentials outside Git.
2. CTRL01: copy the forwarder app. Create the spool directory, run
   `python -m dashboard.event_spool --execute` followed by
   `python -m dashboard.learner_spool --execute` with their required scoped paths
   (the existing controller service includes both) on a schedule under the staff
   account, and grant `splunkfwd` read-only access through a staff-only group
   (`0750` directories, `0640` files). No participant or world access.
3. Review both `monitor://` paths: `/var/lib/netstrike/event-spool` must route only
   to `netstrike_staff`; `/var/lib/netstrike/learner-event-spool` routes to `netstrike`.
4. Provision hosts with both `deployment_version` and `exercise_run_id`
   (`scripts/provision.sh`), so every source is tagged with the run ID.
5. Review `lookups/netstrike_expected_sources.csv` (`required`, `max_age_seconds`).
   The required application sources cover scenario control, identity-slice
   automation, the active identity-action adapter, and facilitator readiness.
   One-time setup and scenario-action sources are listed as optional so their
   expected absence or age does not block the global freshness alert.

## Acceptance checklist (to run live and record in #102)

The [November 4 telemetry evidence](../docs/offline-bundle-provisioning-validation.md#november-4-telemetry-readiness-and-alert-evidence)
records all 25 expected sources, intentional optional `IDLE` states, required
PowerShell `STALE`, and a scheduled source-freshness alert trigger. Reuse it for
status classification and live alert triggering; it is not an all-healthy
readiness result or source-by-source run-ID evidence.

- [ ] `NetStrike Probe - Run ID by source` with a fresh run ID shows every
      identity-slice source (application and Windows).
- [ ] `NetStrike Health - Source freshness` (an alert that returns rows only when a
      required source is MISSING/STALE; `Source overview` lists all statuses) flags a
      deliberately stopped source before participants enter.
- [ ] As a participant: `index=netstrike_staff` and `_internal` are refused, and no
      `netstrike:event:v1` events appear (`NetStrike Access - Participant index isolation` returns 0).
- [ ] `NetStrike Access - Role definitions` output saved as evidence.
- [ ] Participant searches return rows and show no answer labels.
- [ ] Learner audit searches preserve assigned exercise/run/event IDs and typed
      application facts; compare independent Raw Events with the separate local
      projection using [the learner checker](../docs/learner-telemetry-comparison.md),
      not the canonical-contract `dashboard.telemetry_check` helper. A file match
      is not live search/role/ingestion acceptance.
- [ ] Check for duplicates/gaps and compare with `python -m dashboard.telemetry_check` (#158).
- [ ] `NetStrike Health - Ingestion volume by source` measured during a rehearsal.
- [ ] Redeploy to a clean Splunk from this directory and re-run the checks; save evidence outside reverted VMs.

## View triggered alerts

1. In Splunk Web, click **Activity**, then **Triggered Alerts**.
2. Set **App** to **NetStrike Staff (netstrike_staff)**. If needed, set **Owner**
   to **All owners** and **Alert name** to **NetStrike Health - Source freshness**.
3. Find the trigger by time and click **View Results** to inspect the required
   `MISSING`/`STALE` source rows returned by that execution. The separate
   **NetStrike Health - Source overview** report lists optional `IDLE` and
   `NOT_SEEN` states as well as healthy sources.
4. Preserve the trigger time and result rows with the deployment/run evidence
   outside restored VMs. A trigger proves alert execution; it does not prove
   email/webhook delivery or that required sources have recovered.

## Known risks to verify

- `citef-config/environment.example.json` probes `source="WinEventLog:Security"`, but
  `renderXml = 1` normally yields `XmlWinEventLog:Security`. Searches here use
  `*WinEventLog:*`; check the real `source` value and fix the probe if needed.
- A role without `user` may need extra capabilities for Splunk Web; test the first login.
- `$run_id$` in the probe/guide searches is a token: replace it with the run ID when
  running outside a dashboard.
- Application-event field names (`source.component`, `outcome.status`, ...) rely on the
  v1 schema; confirm after the first real ingest.

Static checks: `python -m unittest splunk/tests/test_splunk_config.py`.
