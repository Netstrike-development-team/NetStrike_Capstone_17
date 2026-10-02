"""Read-only, local application readiness; never certify external range services."""

from __future__ import annotations

import sqlite3
from typing import Callable

from orchestrator.controller import ItemStatus, RunState
from shared.events import EventValidator

SCOPE = "local_application_only"
EXTERNAL_CHECKS = (
    "approved_vm_targets_and_topology",
    "splunk_ingestion_and_access",
    "dns_ntp_and_required_services",
    "vm_snapshot_restore",
    "staff_emergency_stop_access",
    "facilitator_admission_signoff",
)


def _probe(check_id: str, operation: Callable[[], bool]) -> dict:
    """A failed inspection must be a blocker, without leaking exception text."""
    try:
        passed = operation() is True
        code = "matched" if passed else "mismatch"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
        passed, code = False, "inspection_failed"
    return {"check_id": check_id, "passed": passed, "code": code}


def _ledger_matches(service) -> bool:
    run = service.run
    events = service.store.events(run.definition.exercise_id, run.run_id)
    validator = EventValidator()
    for event in events:
        validator.validate(event)
    return (
        [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        and len({event["event_id"] for event in events}) == len(events)
        and all(
            event["run_id"] == run.run_id
            and event["exercise_id"] == run.definition.exercise_id
            for event in events
        )
        and run.sequencer.sequence == len(events)
    )


def _endpoint_matches(run, prepared: bool) -> bool:
    expected = type(run.endpoint_state).baseline().snapshot()
    if run.impact_enabled and prepared:
        expected["processes"]["impact-task-01"]["active"] = True
    return run.endpoint_state.snapshot() == expected


def _simulation_matches(run) -> bool:
    state = run.automation.state
    items = run.controller.items
    return (
        state.baseline_loaded == (items["PRE-01"].status == ItemStatus.DELIVERED)
        and state.history_staged == (items["PRE-02"].status == ItemStatus.DELIVERED)
        and state.session_replays == 0
        and state.discovery_runs == 0
        and not state.persistence_attempted
        and not state.blocked_post_containment_auth
        and not state.adverse_persistence_created
    )


def _impact_matches(run, prepared: bool) -> bool:
    if not run.impact:
        return True
    impact = run.impact
    return (
        impact.prepared == prepared
        and not impact.applied
        and impact.fixture.inspect()["baseline_verified"] is True
        and impact.brief is None
        and impact.validation_event_id is None
        and impact.final_review is None
    )


def application_readiness(service) -> dict:
    """Inspect a consistent pre-play snapshot; no events, file writes or actions."""
    run = service.run
    with run.state_lock:
        controller = run.controller
        pre_items = [
            item
            for item in run.definition.items
            if item.trigger.trigger_type == "pre_exercise"
        ]
        prepared = bool(
            run.impact and controller.items["PRE-03"].status == ItemStatus.DELIVERED
        )
        checks = [
            _probe(
                "pre_play_state",
                lambda: controller.state == RunState.READY
                and controller.elapsed_seconds == 0
                and not controller.checkpoint_results,
            ),
            _probe(
                "required_handlers",
                lambda: all(
                    callable(controller.handlers.get(item.action_id))
                    for item in run.definition.items
                    if item.action_id is not None
                ),
            ),
            _probe(
                "preparation_progress",
                lambda: all(
                    controller.items[item.item_id].status
                    in {ItemStatus.PENDING, ItemStatus.DELIVERED}
                    for item in pre_items
                ),
            ),
            _probe(
                "identity_baseline",
                lambda: not run.identity_state.readiness_mismatches(),
            ),
            _probe("endpoint_baseline", lambda: _endpoint_matches(run, prepared)),
            _probe("simulation_baseline", lambda: _simulation_matches(run)),
            _probe("sso_baseline", lambda: not service.sso.baseline_mismatches()),
            _probe(
                "scheduled_mfa_baseline",
                lambda: not run.mfa.snapshot()["history"]
                and run.mfa.snapshot()["pending"] is None,
            ),
            _probe(
                "submissions_empty", lambda: not service.store.submissions(run.run_id)
            ),
            _probe("identity_audit_empty", lambda: not service.identity_timeline()),
            _probe("event_ledger", lambda: _ledger_matches(service)),
        ]
        if run.cloud_enabled:
            checks.append(
                _probe(
                    "cloud_baseline",
                    lambda: not run.cloud.state.readiness_mismatches()
                    and not run.cloud.audit
                    and run.cloud.assessment is None,
                )
            )
        if run.impact_enabled:
            checks.append(
                _probe("impact_baseline", lambda: _impact_matches(run, prepared))
            )
        can_prepare = all(check["passed"] for check in checks)
        preparation_complete = bool(pre_items) and all(
            controller.items[item.item_id].status == ItemStatus.DELIVERED
            for item in pre_items
        )
        return {
            "scope": SCOPE,
            "exercise_id": run.definition.exercise_id,
            "run_id": run.run_id,
            "scenario_id": run.definition.scenario_id,
            "state": controller.state.value,
            "checks": checks,
            "blockers": [check["check_id"] for check in checks if not check["passed"]],
            "preparation_complete": preparation_complete,
            "ready_to_prepare": can_prepare,
            "ready_to_start": can_prepare and preparation_complete,
            "external_readiness_verified": False,
            "external_checks": [
                {"check_id": item, "status": "not_checked"} for item in EXTERNAL_CHECKS
            ],
        }
