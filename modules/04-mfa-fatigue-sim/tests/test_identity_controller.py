from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODULE))

from identity_controller import (
    AuthenticationError,
    IdentityController,
    Principal,
    load_token_principals,
)
from shared.events import EventValidator

NOW = datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)
ENGINE_TOKEN = "engine-token-0001"
LEARNER_TOKEN = "learner-token-001"
SIMULATED_USER_TOKEN = "sim-user-token-01"


@pytest.fixture
def controller_system():
    events = []
    controller = IdentityController(
        exercise_id="silent-spider",
        run_id="run-http-001",
        tokens={
            ENGINE_TOKEN: Principal("scenario-engine", "scenario_engine"),
            LEARNER_TOKEN: Principal("learner-01", "identity_responder"),
            SIMULATED_USER_TOKEN: Principal("sarah-roleplayer", "simulated_user"),
        },
        event_sink=events.append,
        approval_threshold=2,
        clock=lambda: NOW,
    )
    return controller, events


def payload(action_id="identity.mfa.challenge.record", **overrides):
    value = {
        "action_id": action_id,
        "target": {"type": "identity", "id": "sarah"},
        "idempotency_key": "http-action-001",
        "parameters": {},
        "dry_run": False,
        "timeout_seconds": 5,
    }
    value.update(overrides)
    return value


def test_token_configuration_is_strict():
    principals = load_token_principals(
        '{"sixteen-char-token": {"actor_id": "engine", "role": "scenario_engine"}}'
    )
    assert principals["sixteen-char-token"].role == "scenario_engine"
    with pytest.raises(ValueError, match="at least 16"):
        load_token_principals('{"short": {"actor_id": "x", "role": "facilitator"}}')


def test_authentication_rejects_missing_and_invalid_tokens(controller_system):
    controller, _events = controller_system
    with pytest.raises(AuthenticationError):
        controller.authenticate(None)
    with pytest.raises(AuthenticationError):
        controller.authenticate("Bearer incorrect-token-value")


def test_server_owned_principal_drives_authorization(controller_system):
    controller, events = controller_system
    principal = controller.authenticate(f"Bearer {ENGINE_TOKEN}")
    result = controller.submit(principal, payload())
    assert result["successful"] is True
    assert controller.state.mfa["sarah"] == {
        "push_count": 1,
        "decision": "denied",
    }
    assert events[0]["actor"]["id"] == "scenario-engine"
    assert events[0]["actor"]["role"] == "scenario_engine"
    for event in events:
        EventValidator().validate(event)


def test_client_cannot_forge_actor_or_run(controller_system):
    controller, _events = controller_system
    principal = controller.authenticate(f"Bearer {LEARNER_TOKEN}")
    forged = payload(actor={"id": "facilitator"}, run_id="another-run")
    with pytest.raises(ValueError, match="unsupported fields"):
        controller.submit(principal, forged)


def test_valid_token_with_wrong_role_is_denied(controller_system):
    controller, _events = controller_system
    principal = controller.authenticate(f"Bearer {LEARNER_TOKEN}")
    result = controller.submit(principal, payload())
    assert result["error_code"] == "role_denied"
    assert controller.state.mfa["sarah"]["push_count"] == 0


def test_simulated_user_decision_uses_separate_role(controller_system):
    controller, _events = controller_system
    principal = controller.authenticate(f"Bearer {SIMULATED_USER_TOKEN}")
    result = controller.submit(
        principal,
        payload(
            "identity.mfa.decision.record",
            idempotency_key="decision-001",
            parameters={"approved": True},
        ),
    )
    assert result["successful"] is True
    assert controller.state.mfa["sarah"]["decision"] == "approved"


def test_http_boundary_and_removed_legacy_routes(controller_system, monkeypatch):
    controller, _events = controller_system
    import mock_okta_api

    monkeypatch.setattr(mock_okta_api, "controller", controller)
    client = mock_okta_api.app.test_client()

    assert client.post("/api/action", json=payload()).status_code == 401
    response = client.post(
        "/api/action",
        json=payload(),
        headers={"Authorization": f"Bearer {ENGINE_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "executed"
    assert client.post("/api/push", json={}).status_code == 410
    assert client.post("/api/human-approve", json={}).status_code == 410
    assert client.post("/api/reset", json={}).status_code == 410
