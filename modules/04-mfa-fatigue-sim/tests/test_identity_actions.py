from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODULE))

from identity_actions import SyntheticIdentityState, register_identity_actions
from shared.actions import ActionRegistry, SafeActionAdapter, make_action_request
from shared.events import EventContext, EventValidator, entity

NOW = datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def identity_system():
    state = SyntheticIdentityState.baseline()
    registry = ActionRegistry()
    register_identity_actions(registry, state)
    events = []
    adapter = SafeActionAdapter(
        context=EventContext(
            exercise_id="silent-spider",
            run_id="run-identity-001",
            source_kind="action_adapter",
            source_component="identity-action-adapter",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=lambda _exercise, _run: "running",
        event_sink=events.append,
        clock=lambda: NOW,
    )
    return state, adapter, events


def action_request(action_id, target_type, target_id, key):
    return make_action_request(
        exercise_id="silent-spider",
        run_id="run-identity-001",
        actor=entity("participant", "learner-01", role="identity_responder"),
        action_id=action_id,
        target=entity(target_type, target_id),
        idempotency_key=key,
        parameters={},
        dry_run=False,
        timeout_seconds=10,
        clock=lambda: NOW,
    )


@pytest.mark.parametrize(
    ("action_id", "target_type", "target_id", "collection", "field", "expected"),
    [
        (
            "identity.session.revoke",
            "session",
            "sess-red-01",
            "sessions",
            "active",
            False,
        ),
        (
            "identity.factor.remove",
            "mfa_factor",
            "factor-red-01",
            "factors",
            "active",
            False,
        ),
        (
            "identity.account.disable",
            "identity",
            "sarah",
            "identities",
            "enabled",
            False,
        ),
    ],
)
def test_containment_actions_change_only_allowlisted_state(
    identity_system, action_id, target_type, target_id, collection, field, expected
):
    state, adapter, events = identity_system
    before = state.snapshot()
    request = action_request(action_id, target_type, target_id, f"test-{action_id}")

    result = adapter.execute(request)

    assert result["status"] == "executed"
    assert getattr(state, collection)[target_id][field] is expected
    assert state.snapshot() != before
    assert all(event["run_id"] == "run-identity-001" for event in events)
    for event in events:
        EventValidator().validate(event)


def test_credential_reset_rotates_version_without_storing_secret(identity_system):
    state, adapter, _events = identity_system
    result = adapter.execute(
        action_request("identity.credential.reset", "identity", "sarah", "reset-sarah")
    )
    assert result["successful"] is True
    assert state.identities["sarah"]["credential_version"] == 2
    assert "password" not in state.identities["sarah"]


def test_dry_run_preserves_baseline(identity_system):
    state, adapter, _events = identity_system
    before = state.snapshot()
    request = action_request(
        "identity.account.disable", "identity", "sarah", "dry-run-disable"
    )
    request["dry_run"] = True
    result = adapter.execute(request)
    assert result["status"] == "dry_run"
    assert state.snapshot() == before


def test_action_is_reversible(identity_system):
    state, adapter, _events = identity_system
    request = action_request(
        "identity.session.revoke", "session", "sess-red-01", "revoke-red-session"
    )
    adapter.execute(request)
    assert state.sessions["sess-red-01"]["active"] is False

    adapter.rollback(
        request["request_id"],
        entity("facilitator", "fac-01", role="facilitator"),
    )
    assert state.sessions["sess-red-01"]["active"] is True


def test_wrong_identity_and_session_fail_closed(identity_system):
    state, adapter, _events = identity_system
    before = state.snapshot()
    result = adapter.execute(
        action_request(
            "identity.session.revoke", "session", "sess-external", "bad-target"
        )
    )
    assert result["error_code"] == "target_denied"
    assert state.snapshot() == before


def test_replay_does_not_repeat_credential_rotation(identity_system):
    state, adapter, _events = identity_system
    request = action_request(
        "identity.credential.reset", "identity", "sarah", "rotate-once"
    )
    adapter.execute(request)
    replay = adapter.execute(request)
    assert replay["cached"] is True
    assert state.identities["sarah"]["credential_version"] == 2
