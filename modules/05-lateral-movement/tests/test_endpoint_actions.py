from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODULE))

from endpoint_actions import EndpointAdState, build_endpoint_adapter
from shared.actions import make_action_request
from shared.events import EventValidator, entity

NOW = datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc)
EXERCISE_ID = "silent-spider"
RUN_ID = "run-endpoint-001"


def build_system(state=None, run_state="running"):
    endpoint_state = state or EndpointAdState.baseline()
    current = {"state": run_state}
    events = []
    adapter = build_endpoint_adapter(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        state=endpoint_state,
        run_state=lambda _exercise, _run: current["state"],
        event_sink=events.append,
    )
    adapter.clock = lambda: NOW
    adapter.events.clock = lambda: NOW
    return endpoint_state, adapter, events, current


def action_request(
    action_id,
    target_type,
    target_id,
    key,
    *,
    role="endpoint_responder",
):
    return make_action_request(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        actor=entity("participant", "learner-01", role=role),
        action_id=action_id,
        target=entity(target_type, target_id),
        idempotency_key=key,
        parameters={},
        dry_run=False,
        timeout_seconds=10,
        clock=lambda: NOW,
    )


def test_isolation_retains_controller_visibility_and_emits_valid_events():
    state, adapter, events, _current = build_system()

    result = adapter.execute(
        action_request("endpoint.host.isolate", "host", "FIN-WS01", "isolate-fin-ws01")
    )

    assert result["status"] == "executed"
    assert state.hosts["FIN-WS01"] == {
        "isolated": True,
        "remote_path_enabled": False,
        "controller_visible": True,
    }
    assert events
    for event in events:
        EventValidator().validate(event)
    assert {event["phase"] for event in events if event["phase"] != "control"} == {
        "endpoint_ad"
    }


def test_evidence_bundle_can_be_preserved():
    state, adapter, _events, _current = build_system()

    result = adapter.execute(
        action_request(
            "evidence.artifact.preserve",
            "evidence_artifact",
            "FIN-WS01-discovery-bundle",
            "preserve-discovery",
        )
    )

    assert result["successful"] is True
    artifact = state.artifacts["FIN-WS01-discovery-bundle"]
    assert artifact["preserved"] is True
    assert len(artifact["sha256"]) == 64


def test_adverse_account_can_be_disabled_then_removed():
    state, adapter, _events, _current = build_system(EndpointAdState.adverse_fixture())

    disabled = adapter.execute(
        action_request(
            "ad.account.disable",
            "directory_account",
            "svc-print-sync",
            "disable-persistence-account",
        )
    )
    removed = adapter.execute(
        action_request(
            "ad.persistence.remove",
            "directory_account",
            "svc-print-sync",
            "remove-persistence-account",
        )
    )

    assert disabled["successful"] is True
    assert removed["successful"] is True
    assert state.accounts["svc-print-sync"] == {
        "exists": False,
        "enabled": False,
        "groups": [],
    }


def test_disabling_absent_account_returns_safe_failure():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "ad.account.disable",
            "directory_account",
            "svc-print-sync",
            "disable-absent-account",
        )
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "target_not_present"
    assert state.snapshot() == before


def test_impact_process_can_be_stopped():
    state, adapter, _events, _current = build_system(EndpointAdState.adverse_fixture())

    result = adapter.execute(
        action_request(
            "endpoint.process.stop",
            "process",
            "impact-task-01",
            "stop-impact-task",
        )
    )

    assert result["successful"] is True
    assert state.processes["impact-task-01"]["active"] is False


def test_target_allowlist_fails_closed_without_state_change():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()

    result = adapter.execute(
        action_request("endpoint.host.isolate", "host", "HR-WS99", "reject-other-host")
    )

    assert result["status"] == "denied"
    assert result["error_code"] == "target_denied"
    assert state.snapshot() == before


def test_idempotent_replay_does_not_repeat_action():
    state, adapter, _events, _current = build_system()
    request = action_request(
        "endpoint.host.isolate", "host", "FIN-WS01", "isolate-once"
    )

    first = adapter.execute(request)
    first_snapshot = state.snapshot()
    replay = adapter.execute(request)

    assert first["cached"] is False
    assert replay["cached"] is True
    assert state.snapshot() == first_snapshot
    assert len(state._rollbacks) == 1  # pylint: disable=protected-access


def test_action_rollback_restores_exact_previous_state():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()
    request = action_request(
        "endpoint.host.isolate", "host", "FIN-WS01", "rollback-isolation"
    )
    adapter.execute(request)

    changes = adapter.rollback(
        request["request_id"], entity("facilitator", "fac-01", role="facilitator")
    )

    assert changes == ("restored pre-action endpoint/AD state",)
    assert state.snapshot() == before


def test_reset_is_denied_while_run_is_active():
    state, adapter, _events, _current = build_system(EndpointAdState.adverse_fixture())
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "exercise.endpoint.reset",
            "exercise_run",
            RUN_ID,
            "reset-running",
            role="technical_operator",
        )
    )

    assert result["error_code"] == "invalid_run_state"
    assert state.snapshot() == before


def test_stopped_run_can_reset_and_validate_readiness():
    state, adapter, events, current = build_system(
        EndpointAdState.adverse_fixture(), run_state="stopped"
    )

    reset = adapter.execute(
        action_request(
            "exercise.endpoint.reset",
            "exercise_run",
            RUN_ID,
            "reset-stopped",
            role="technical_operator",
        )
    )
    current["state"] = "ready"
    readiness = adapter.execute(
        action_request(
            "exercise.endpoint.readiness.validate",
            "exercise_run",
            RUN_ID,
            "validate-ready",
            role="technical_operator",
        )
    )

    assert reset["successful"] is True
    assert readiness["successful"] is True
    assert state.snapshot() == EndpointAdState.baseline().snapshot()
    for event in events:
        EventValidator().validate(event)


@pytest.mark.parametrize(
    ("section", "mutate"),
    [
        (
            "accounts",
            lambda state: state.accounts["svc-print-sync"].update(exists=True),
        ),
        (
            "processes",
            lambda state: state.processes["impact-task-01"].update(active=True),
        ),
    ],
)
def test_readiness_identifies_dirty_state(section, mutate):
    state, adapter, _events, _current = build_system(run_state="ready")
    mutate(state)

    result = adapter.execute(
        action_request(
            "exercise.endpoint.readiness.validate",
            "exercise_run",
            RUN_ID,
            f"dirty-{section}",
            role="technical_operator",
        )
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "baseline_mismatch"
    assert section in result["message"]


def test_reset_can_be_rolled_back_for_recovery():
    state, adapter, _events, _current = build_system(
        EndpointAdState.adverse_fixture(), run_state="stopped"
    )
    before = state.snapshot()
    request = action_request(
        "exercise.endpoint.reset",
        "exercise_run",
        RUN_ID,
        "reset-with-rollback",
        role="technical_operator",
    )
    adapter.execute(request)

    adapter.rollback(
        request["request_id"], entity("facilitator", "fac-01", role="facilitator")
    )

    assert state.snapshot() == before
