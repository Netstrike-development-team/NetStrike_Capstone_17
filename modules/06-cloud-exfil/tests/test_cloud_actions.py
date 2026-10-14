from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODULE))

from cloud_actions import (
    BUCKET_ID,
    KEY_ID,
    PRINCIPAL_ID,
    MockCloudState,
    build_cloud_adapter,
)
from shared.actions import ActionExecutionError, make_action_request
from shared.events import EventValidator, entity

NOW = datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)
EXERCISE_ID = "silent-spider"
RUN_ID = "run-cloud-001"


def build_system(state=None, run_state="running"):
    cloud_state = state or MockCloudState.baseline()
    current = {"state": run_state}
    events = []
    adapter = build_cloud_adapter(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        state=cloud_state,
        run_state=lambda _exercise, _run: current["state"],
        event_sink=events.append,
    )
    adapter.clock = lambda: NOW
    adapter.events.clock = lambda: NOW
    return cloud_state, adapter, events, current


def action_request(
    action_id,
    target_type,
    target_id,
    key,
    *,
    role="cloud_responder",
    dry_run=False,
):
    return make_action_request(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        actor=entity("participant", "learner-01", role=role),
        action_id=action_id,
        target=entity(target_type, target_id),
        idempotency_key=key,
        parameters={},
        dry_run=dry_run,
        timeout_seconds=10,
        clock=lambda: NOW,
    )


def test_baseline_contains_only_opaque_synthetic_key_metadata():
    state = MockCloudState.baseline()

    assert state.keys[KEY_ID] == {
        "principal_id": PRINCIPAL_ID,
        "active": True,
        "synthetic": True,
    }
    assert "secret" not in state.keys[KEY_ID]
    assert "token" not in state.keys[KEY_ID]
    assert state.access_decision(PRINCIPAL_ID, KEY_ID, BUCKET_ID, bulk=False) == (
        True,
        "allowed",
    )


def test_access_decision_rejects_key_principal_mismatch():
    state = MockCloudState.baseline()
    state.keys[KEY_ID]["principal_id"] = "different-principal"

    assert state.access_decision(PRINCIPAL_ID, KEY_ID, BUCKET_ID, bulk=False) == (
        False,
        "key_principal_mismatch",
    )


def test_key_revocation_blocks_future_access_and_emits_valid_events():
    state, adapter, events, _current = build_system()

    result = adapter.execute(
        action_request("cloud.key.revoke", "cloud_key", KEY_ID, "revoke-key")
    )

    assert result["status"] == "executed"
    assert state.keys[KEY_ID]["active"] is False
    assert state.access_decision(PRINCIPAL_ID, KEY_ID, BUCKET_ID, bulk=False) == (
        False,
        "key_revoked",
    )
    for event in events:
        EventValidator().validate(event)
    assert {event["phase"] for event in events if event["phase"] != "control"} == {
        "cloud"
    }


def test_disabling_principal_atomically_revokes_its_keys():
    state, adapter, _events, _current = build_system()

    result = adapter.execute(
        action_request(
            "cloud.principal.disable",
            "cloud_principal",
            PRINCIPAL_ID,
            "disable-principal",
        )
    )

    assert result["successful"] is True
    assert state.principals[PRINCIPAL_ID]["enabled"] is False
    assert state.keys[KEY_ID]["active"] is False
    assert state.access_decision(PRINCIPAL_ID, KEY_ID, BUCKET_ID, bulk=False) == (
        False,
        "principal_disabled",
    )


def test_policy_restore_reinstates_approved_hash_and_denies_bulk_access():
    state, adapter, _events, _current = build_system(MockCloudState.adverse_fixture())
    approved_hash = MockCloudState.baseline().buckets[BUCKET_ID]["approved_policy_hash"]

    result = adapter.execute(
        action_request(
            "cloud.policy.restore",
            "cloud_bucket",
            BUCKET_ID,
            "restore-policy",
        )
    )

    assert result["successful"] is True
    bucket = state.buckets[BUCKET_ID]
    assert bucket["policy_hash"] == approved_hash
    assert bucket["bulk_access_allowed"] is False
    assert state.exposure[BUCKET_ID]["confirmed_count"] == 25
    assert state.access_decision(PRINCIPAL_ID, KEY_ID, BUCKET_ID, bulk=True) == (
        False,
        "policy_denied",
    )


def test_adverse_fixture_has_deterministic_confirmed_exposure():
    state = MockCloudState.adverse_fixture()

    exposure = state.exposure[BUCKET_ID]
    assert exposure["confirmed_count"] == 25
    assert len(exposure["accessed_record_ids"]) == 25
    assert exposure["last_outcome"] == "full_exposure"
    assert state.buckets[BUCKET_ID]["bulk_access_allowed"] is True


@pytest.mark.parametrize(
    ("principal_id", "key_id", "bucket_id", "reason"),
    [
        ("external-principal", KEY_ID, BUCKET_ID, "principal_unknown"),
        (PRINCIPAL_ID, "external-key", BUCKET_ID, "key_unknown"),
        (PRINCIPAL_ID, KEY_ID, "external-bucket", "bucket_unknown"),
    ],
)
def test_access_decision_fails_closed_for_unknown_objects(
    principal_id, key_id, bucket_id, reason
):
    state = MockCloudState.baseline()

    assert state.access_decision(principal_id, key_id, bucket_id, bulk=True) == (
        False,
        reason,
    )


def test_wrong_bucket_fails_closed_without_state_change():
    state, adapter, _events, _current = build_system(MockCloudState.adverse_fixture())
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "cloud.policy.restore",
            "cloud_bucket",
            "external-production-bucket",
            "reject-external-bucket",
        )
    )

    assert result["status"] == "denied"
    assert result["error_code"] == "target_denied"
    assert state.snapshot() == before


def test_wrong_role_fails_closed_without_state_change():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "cloud.key.revoke",
            "cloud_key",
            KEY_ID,
            "reject-wrong-role",
            role="endpoint_responder",
        )
    )

    assert result["status"] == "denied"
    assert result["error_code"] == "role_denied"
    assert state.snapshot() == before


def test_dry_run_performs_policy_checks_without_mutation():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "cloud.key.revoke",
            "cloud_key",
            KEY_ID,
            "dry-run-key",
            dry_run=True,
        )
    )

    assert result["status"] == "dry_run"
    assert state.snapshot() == before


def test_unexpected_parameters_are_denied_without_mutation():
    state, adapter, _events, _current = build_system()
    before = state.snapshot()
    request = action_request(
        "cloud.key.revoke", "cloud_key", KEY_ID, "unexpected-parameters"
    )
    request["parameters"] = {"force": True}

    result = adapter.execute(request)

    assert result["status"] == "denied"
    assert result["error_code"] == "invalid_parameters"
    assert state.snapshot() == before


def test_idempotent_replay_does_not_repeat_action():
    state, adapter, _events, _current = build_system()
    request = action_request("cloud.key.revoke", "cloud_key", KEY_ID, "revoke-key-once")

    first = adapter.execute(request)
    first_snapshot = state.snapshot()
    replay = adapter.execute(request)

    assert first["cached"] is False
    assert replay["cached"] is True
    assert state.snapshot() == first_snapshot
    assert len(state._rollbacks) == 1  # pylint: disable=protected-access


def test_action_rollback_restores_exact_previous_state():
    state, adapter, _events, _current = build_system(MockCloudState.adverse_fixture())
    before = state.snapshot()
    request = action_request(
        "cloud.policy.restore", "cloud_bucket", BUCKET_ID, "rollback-policy"
    )
    adapter.execute(request)

    changes = adapter.rollback(
        request["request_id"], entity("facilitator", "fac-01", role="facilitator")
    )

    assert changes == ("restored pre-action mock-cloud state",)
    assert state.snapshot() == before

    with pytest.raises(ActionExecutionError, match="already-used rollback token"):
        adapter.rollback(
            request["request_id"],
            entity("facilitator", "fac-01", role="facilitator"),
        )


def test_reset_is_denied_while_run_is_active():
    state, adapter, _events, _current = build_system(MockCloudState.adverse_fixture())
    before = state.snapshot()

    result = adapter.execute(
        action_request(
            "exercise.cloud.reset",
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
        MockCloudState.adverse_fixture(), run_state="stopped"
    )

    reset = adapter.execute(
        action_request(
            "exercise.cloud.reset",
            "exercise_run",
            RUN_ID,
            "reset-stopped",
            role="technical_operator",
        )
    )
    current["state"] = "ready"
    readiness = adapter.execute(
        action_request(
            "exercise.cloud.readiness.validate",
            "exercise_run",
            RUN_ID,
            "validate-ready",
            role="technical_operator",
        )
    )

    assert reset["successful"] is True
    assert readiness["successful"] is True
    assert state.snapshot() == MockCloudState.baseline().snapshot()
    for event in events:
        EventValidator().validate(event)


@pytest.mark.parametrize(
    ("section", "mutate"),
    [
        (
            "principals",
            lambda state: state.principals[PRINCIPAL_ID].update(enabled=False),
        ),
        ("keys", lambda state: state.keys[KEY_ID].update(active=False)),
        (
            "buckets",
            lambda state: state.buckets[BUCKET_ID].update(bulk_access_allowed=True),
        ),
        (
            "exposure",
            lambda state: state.exposure[BUCKET_ID].update(confirmed_count=1),
        ),
    ],
)
def test_readiness_identifies_dirty_state(section, mutate):
    state, adapter, _events, _current = build_system(run_state="ready")
    mutate(state)

    result = adapter.execute(
        action_request(
            "exercise.cloud.readiness.validate",
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
        MockCloudState.adverse_fixture(), run_state="stopped"
    )
    before = state.snapshot()
    request = action_request(
        "exercise.cloud.reset",
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
