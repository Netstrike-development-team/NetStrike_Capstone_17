# NetStrike Splunk content (#102)

Versioned, secret-free Splunk Enterprise 10.0.1 content. **Nothing here has been
deployed or validated against a live Splunk**; `splunk_ingestion_verified` stays
false until the acceptance steps below are run and evidence is recorded in #102.

| Path | Deploy to | Purpose |
|---|---|---|
| `staff/netstrike_staff` | Splunk server (`$SPLUNK_HOME/etc/apps`) | Indexes, roles, parsing, data-health, access checks, run probes, DP1 solution-guide searches. Facilitator-only. |
| `participant/netstrike_participant` | Splunk server | Neutral investigation searches over `netstrike` only. No staff index, answers or checkpoint logic. |
| `forwarder/netstrike_app_events_inputs` | CTRL01 Universal Forwarder (`splunkfwd`) | Monitored-file input for committed `batch-*/events.jsonl` spool batches (#130). |

Windows Security/PowerShell/Sysmon and Linux inputs already come from
`citef-config/roles/*_telemetry`; they are not duplicated here.

## Design decisions

- **Two indexes.** `netstrike` (CITEF-approved, participant-searchable) holds host
  telemetry. The canonical application ledger contains facilitator/evaluator events
  and answer labels, so it goes to **`netstrike_staff`**, which only
  `netstrike_facilitator` can search. A visibility field is not access control, so
  no `srchFilter` is relied on. **`netstrike_staff` is not in the CITEF approval
  record; confirm with the range administrator.**
- **Retention** is the approved one day (`frozenTimePeriodInSecs = 86400`, hot
  buckets capped at a day). Splunk freezes whole buckets, so expect data to persist
  slightly longer. Events with timestamps older than a day (backdated PRE-02 history)
  may be frozen almost immediately.
- **Roles.** `netstrike_participant` imports nothing. Do not also give participants
  the built-in `user` role: Splunk unions role permissions, so `user` exposes
  `netstrike_staff` (verified live). `netstrike_facilitator` imports `power`. Assign
  real users to them; none exist in the repo.
- **Participant application events.** No participant-safe application feed exists
  (`docs/event-spool.md`), so participants get host telemetry only.
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
  [clean-deployment handoff](../docs/full-play-deployment-binding.md); this local
  guard is not a substitute for the live per-source probe or #158 reconciliation.
- **Windows fields** use `rex` on rendered XML (no add-on assumed).
- **Checkpoint 1 = DP1** (identity triage: Sarah, ≥3 artifacts from ≥2 sources,
  per `orchestrator/checkpoints.py`).
- **Licence** limit is 10 GB/day (CITEF record, 2026-10-02); the volume alert fires at 80%.

## Deploy

1. Splunk server: copy the `staff` and `participant` apps, restart, create users and
   assign roles. Store credentials outside Git.
2. CTRL01: copy the forwarder app. Create the spool directory, run
   `python -m dashboard.event_spool --execute` on a schedule under the staff
   account, and grant `splunkfwd` read-only access through a staff-only group
   (`0750` directories, `0640` files). No participant or world access.
3. Adjust `monitor://` in `inputs.conf` if the spool is not `/var/lib/netstrike/event-spool`.
4. Provision hosts with both `deployment_version` and `exercise_run_id`
   (`scripts/provision.sh`), so every source is tagged with the run ID.
5. Review `lookups/netstrike_expected_sources.csv` (`required`, `max_age_seconds`);
   the required set is an assumption for the identity slice.

## Acceptance checklist (to run live and record in #102)

- [ ] `NetStrike Probe - Run ID by source` with a fresh run ID shows every
      identity-slice source (application and Windows).
- [ ] `NetStrike Health - Source freshness` (an alert that returns rows only when a
      required source is MISSING/STALE; `Source overview` lists all statuses) flags a
      deliberately stopped source before participants enter.
- [ ] As a participant: `index=netstrike_staff` and `_internal` are refused, and no
      `netstrike:event:v1` events appear (`NetStrike Access - Participant index isolation` returns 0).
- [ ] `NetStrike Access - Role definitions` output saved as evidence.
- [ ] Participant searches return rows and show no answer labels.
- [ ] Check for duplicates/gaps and compare with `python -m dashboard.telemetry_check` (#158).
- [ ] `NetStrike Health - Ingestion volume by source` measured during a rehearsal.
- [ ] Redeploy to a clean Splunk from this directory and re-run the checks; save evidence outside reverted VMs.

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
