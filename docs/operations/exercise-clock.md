# Supervised exercise clock

The existing server already advances the scenario automatically; this change
supervises that driver rather than replacing the MSEL, scheduler or exercise
duration. It is application runtime safety, not admission approval, Splunk proof
or a new learning objective.

## Staff inspection

`/facilitator` displays the diagnostic status and gates ordinary controls without
hiding emergency stop. See [staff operations](staff-operations.md) for UI behavior
and the limits of a stop request when a process/handler cannot respond.

`GET /api/facilitator/clock` requires a configured facilitator or
technical-operator bearer token. It returns `Cache-Control: no-store`. The same
object is included as `clock` in facilitator state. The public `/health` is
still process liveness only. Participant/evaluator/capture/user roles cannot
read the clock endpoint; participant state does not contain technical diagnostics.

Example response fields:

```json
{
  "scope": "single_process_application_clock",
  "run_id": "example-run",
  "status": "healthy",
  "automatic_delivery_supervised": true,
  "heartbeat_age_seconds": 0.4,
  "stale_after_seconds": 30,
  "successful_ticks": 12,
  "fault_code": null,
  "cleanup_complete": null,
  "fault_audit_persisted": null,
  "external_readiness_verified": false
}
```

| Status | Meaning / permitted recovery |
| --- | --- |
| `healthy` | Attached driver has a recent valid monotonic heartbeat; not external readiness. |
| `unmonitored` | Direct local service/CLI, no ASGI driver ever attached. Explicit manual control remains supported. |
| `stale` | More than 30 seconds since heartbeat; next tick or guarded mutation safety-stops before catch-up. |
| `invalid_clock` | Monotonic time went backward, became non-finite or its provider failed; next mutation safety-stops. |
| `faulted` | Per-run safety latch; delivery/start/resume/actions blocked until successful archive/reset. |
| `detached` | Driver shut down; active play was stopped. No supervised automatic delivery available. |

Inspection is pure: a GET does not tick, stop, audit or repair anything. Therefore
stale/invalid inspection alone can still show a running controller until a tick
or guarded mutation observes it. If the process is entirely frozen, this endpoint
cannot respond or cancel external work; use the range's emergency-stop procedure.

## Delivery and safety behavior

- One-second ticks and staff/participant runtime mutations share the run lock,
  always before scheduler/adapter locks. Reset and snapshots use that boundary
  too, so events/actions cannot accidentally cross into a replacement run.
- Ticks run outside the ASGI event loop. Shutdown requests the loop to exit and
  awaits its current tick before stopping running/paused play. It never marks
  an exercise completed or restores decoys as a side effect.
- Exercise time remains monotonic: paused time is not counted, resume reanchors,
  and explicit advance reanchors the scheduler. Heartbeats continue during pause.
- A heartbeat delay greater than 30 seconds rejects catch-up before the scheduler
  executes overdue items. This is an application-driver budget, not the old
  Ansible reset target and not the 2h50 session length. It accommodates the existing
  bounded handlers but must be checked under range load. A handler that itself
  exceeds the budget is stopped after returning; Python cannot forcibly undo
  already-completed work or safely kill a stuck thread.
- Tick exceptions are sanitized into server-owned codes; no raw exception text,
  paths, credentials or stack traces are returned in clock health/evidence.
- Controller-handled item failures also trigger the latch, even if no exception
  escapes the scheduler. Guards reject an already-failed item before another
  mutation; a failure created inside the current tick is latched when that tick
  returns. This does not undo other work already performed inside that tick.
- Fault cleanup attempts the controller stop, scheduled-MFA cancellation and
  every identity/endpoint/cloud/impact safety adapter, even if earlier audit writes
  failed. It also retries latches if a handler had already stopped the controller.
  Pending MFA is cleared even if its cancellation audit cannot be persisted.
- A single canonical `exercise.clock.faulted` event is attempted per latched
  fault, with shared sequence/run correlation, source
  `exercise-clock-supervisor`, facilitator visibility and a real internal
  `system/exercise-clock` actor. That internal actor has server-granted
  technical-operator control capability; it does not impersonate a human.
  It is included in canonical exports/Patrick's staff-only spool input.
- `cleanup_complete=false` or `fault_audit_persisted=false` means partial failure,
  not a clean stop certificate. Local delivery is latched off regardless. No
  successful remediation, learning-objective grade or range readiness is fabricated.

## Recovery

1. Keep the affected run stopped. Staff may inspect/export evidence, review it,
   invoke emergency stop again and perform the existing explicit impact rollback.
   Do not use Start, Resume or manual delivery to bypass the fault.
2. Preserve canonical evidence and any run-review snapshot outside VMs **before**
   snapshot restoration. A driver reattachment cannot clear the same run's fault.
3. Repair the underlying cause. Use the existing authenticated Reset with a new,
   unused run ID. Only a successful prior-run archive and verified application
   reset clear the latch and reanchor the attached driver's heartbeat.
4. If persistence failed or the ledger has a sequence gap, archive/reset can
   correctly reject the evidence. Preserve the raw database and available files
   for staff diagnosis; do not delete events, rewind the sequence, fabricate missing
   records or present a partial archive as valid. Range snapshot recovery is a
   separately coordinated process, not an automatic audit-repair feature.
5. Recheck local readiness **and** Patrick's external checks before admitting play.

This runtime does not resume a historical exercise after process restart. A new
process constructs a new runtime; do not reuse a historical run ID or treat its
old SQLite evidence as live continuation. Existing readiness checks reject a
reused/inconsistent event ledger. No restart/HA recovery guarantee is introduced.

## Deployment and owner boundaries

Patrick: deploy **one process and one ASGI worker per exercise runtime**. A
duplicate lifespan for the same service is rejected, but this is not a
cross-process lease. Multiple uvicorn/gunicorn workers, overlapping replicas,
rolling replacement and cross-host failover are unsupported for this runtime.
Do not configure them as an availability solution.

During #103/#104 range rehearsal, verify authenticated clock status, continuous
ticks with no browser open, pause/resume behavior under load, intentional safe
stop, orderly service shutdown, evidence export, snapshot restoration and a new
run's local/external baselines. Patrick retains service/Ansible, VM permissions,
UF/Splunk ingestion/access, retention and live acceptance. Anna retains exercise
content and evaluator calibration. Aya owns this application guard and offline
regressions. No deployment or Patrick branch was modified here.

## Local verification

```bash
python -m pytest dashboard/tests/test_clock.py dashboard/tests/test_readiness.py -q
python -m pytest shared/tests dashboard/tests orchestrator/tests scripts/tests -q
python scripts/rehearsal.py --execute --output /tmp/netstrike-clock-rehearsal
python scripts/rehearsal.py --verify /tmp/netstrike-clock-rehearsal
```

Use a fresh evidence output directory. The normal local rehearsal CLI explicitly
uses manual/unmonitored time; its branch/fault regressions do not certify real-time
range operation. The clock suite separately drives the actual ASGI lifespan and
tests tick failure, stale/invalid time, authorization/redaction, concurrent actions,
in-flight shutdown, partial cleanup, archive/reset and preserved per-run evidence.
Strict local-rehearsal CI now includes orchestrator tests as a hard failure gate,
not just the legacy backend job's best-effort tests.
