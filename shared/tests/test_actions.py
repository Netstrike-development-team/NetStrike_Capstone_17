from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from shared.actions import (
    ActionContractError,
    ActionDefinition,
    ActionEffect,
    ActionExecutionError,
    ActionRegistry,
    ActionValidationError,
    ActionValidator,
    SafeActionAdapter,
    make_action_request,
)
from shared.events import EventContext, EventValidator, entity

NOW = datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def action_system():
    state = {"disabled": False, "handler_calls": 0, "rollbacks": 0}
    events = []

    def validate_parameters(parameters):
        if parameters.get("confirm") is not True:
            raise ValueError("confirm must be true")

    def handler(parameters, target, control):
        control.checkpoint(lambda: 10.0)
        state["handler_calls"] += 1
        state["disabled"] = True
        return ActionEffect(
            effects=(f"disabled {target['id']}",),
            rollback_token="identity:sarah:enabled",
            metadata={"synthetic": True},
        )

    def rollback(token, control):
        control.checkpoint(lambda: 10.0)
        assert token == "identity:sarah:enabled"
        state["disabled"] = False
        state["rollbacks"] += 1
        return ("enabled sarah",)

    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            action_id="identity.account.disable",
            phase="identity",
            allowed_roles=frozenset({"identity_responder", "facilitator"}),
            allowed_targets=frozenset({"identity:sarah"}),
            allowed_run_states=frozenset({"running"}),
            max_timeout_seconds=30,
            expected_effects=("disable synthetic identity",),
            rollback_method="restore prior enabled state",
            handler=handler,
            rollback_handler=rollback,
            parameter_validator=validate_parameters,
        )
    )
    adapter = SafeActionAdapter(
        context=EventContext(
            exercise_id="silent-spider",
            run_id="run-001",
            source_kind="action_adapter",
            source_component="safe-action-adapter",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=lambda _exercise, _run: "running",
        event_sink=events.append,
        clock=lambda: NOW,
        monotonic=lambda: 10.0,
    )
    return adapter, state, events


def request(**overrides):
    values = {
        "exercise_id": "silent-spider",
        "run_id": "run-001",
        "actor": entity("participant", "learner-01", role="identity_responder"),
        "action_id": "identity.account.disable",
        "target": entity("identity", "sarah"),
        "idempotency_key": "checkpoint-1-disable-sarah",
        "parameters": {"confirm": True},
        "dry_run": False,
        "timeout_seconds": 20,
        "clock": lambda: NOW,
        "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }
    values.update(overrides)
    return make_action_request(**values)


def test_request_and_result_validate(action_system):
    adapter, state, events = action_system
    action_request = request()
    ActionValidator().validate(action_request)

    result = adapter.execute(action_request)

    assert result["status"] == "executed"
    assert result["successful"] is True
    assert state["disabled"] is True
    assert [event["event_type"] for event in events] == [
        "action.requested",
        "action.authorization.granted",
        "action.execution.started",
        "action.execution.completed",
    ]
    for event in events:
        EventValidator().validate(event)


def test_dry_run_never_invokes_handler(action_system):
    adapter, state, _events = action_system
    result = adapter.execute(request(dry_run=True))
    assert result["status"] == "dry_run"
    assert state["handler_calls"] == 0


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"actor": entity("participant", "observer", role="observer")}, "role_denied"),
        ({"target": entity("identity", "external-user")}, "target_denied"),
        ({"action_id": "identity.account.delete"}, "unregistered_action"),
        ({"timeout_seconds": 31}, "timeout_exceeds_policy"),
        ({"parameters": {"confirm": False}}, "invalid_parameters"),
        ({"run_id": "another-run"}, "correlation_mismatch"),
    ],
)
def test_policy_failures_are_denied(action_system, changes, code):
    adapter, state, _events = action_system
    result = adapter.execute(request(**changes))
    assert result["status"] == "denied"
    assert result["error_code"] == code
    assert state["handler_calls"] == 0


def test_idempotent_replay_does_not_repeat_side_effect(action_system):
    adapter, state, _events = action_system
    first = adapter.execute(request())
    second_request = request(request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    second = adapter.execute(second_request)
    assert first["cached"] is False
    assert second["cached"] is True
    assert state["handler_calls"] == 1


def test_idempotency_key_reuse_for_different_action_fails(action_system):
    adapter, _state, _events = action_system
    adapter.execute(request())
    changed = request(
        request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        parameters={"confirm": True, "reason": "different"},
    )
    result = adapter.execute(changed)
    assert result["error_code"] == "idempotency_conflict"


def test_fail_safe_blocks_future_actions(action_system):
    adapter, state, events = action_system
    cancelled = adapter.activate_fail_safe(
        "run-001",
        entity("facilitator", "fac-01", role="facilitator"),
        "target mismatch",
    )
    result = adapter.execute(request())
    assert cancelled == 0
    assert result["error_code"] == "run_stopped"
    assert state["handler_calls"] == 0
    assert events[0]["event_type"] == "action.fail_safe.activated"


def test_fail_safe_requires_control_role(action_system):
    adapter, _state, _events = action_system
    with pytest.raises(ActionContractError, match="exercise-control"):
        adapter.activate_fail_safe(
            "run-001",
            entity("participant", "learner-01", role="identity_responder"),
            "test",
        )


def test_successful_execution_can_be_rolled_back(action_system):
    adapter, state, events = action_system
    adapter.execute(request())
    changes = adapter.rollback(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        entity("facilitator", "fac-01", role="facilitator"),
    )
    assert changes == ("enabled sarah",)
    assert state["disabled"] is False
    assert state["rollbacks"] == 1
    assert events[-1]["event_type"] == "action.rollback.completed"


def test_rollback_requires_control_role(action_system):
    adapter, _state, _events = action_system
    adapter.execute(request())
    with pytest.raises(ActionContractError, match="exercise-control"):
        adapter.rollback(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            entity("participant", "learner-01", role="identity_responder"),
        )


def test_schema_rejects_unknown_fields_and_major_versions():
    invalid = deepcopy(request())
    invalid["unexpected"] = True
    with pytest.raises(ActionValidationError):
        ActionValidator().validate(invalid)
    invalid = request()
    invalid["schema_version"] = "2.0.0"
    with pytest.raises(ActionValidationError, match="unsupported"):
        ActionValidator().validate(invalid)


def test_secret_parameters_are_redacted():
    action_request = request(parameters={"confirm": True, "access_token": "secret"})
    assert action_request["parameters"]["access_token"] == "[REDACTED]"


def test_expected_handler_failure_preserves_safe_code_and_message():
    registry = ActionRegistry()

    def fail_readiness(_parameters, _target, _control):
        raise ActionExecutionError("baseline_mismatch", "Synthetic baseline differs")

    registry.register(
        ActionDefinition(
            action_id="exercise.readiness.validate",
            phase="setup",
            allowed_roles=frozenset({"technical_operator"}),
            allowed_targets=frozenset({"exercise_run:run-test-001"}),
            allowed_run_states=frozenset({"stopped"}),
            max_timeout_seconds=10,
            expected_effects=("validate baseline",),
            rollback_method="not required for validation",
            handler=fail_readiness,
            rollback_handler=lambda _token, _control: (),
        )
    )
    adapter = SafeActionAdapter(
        context=EventContext(
            exercise_id="silent-spider",
            run_id="run-test-001",
            source_kind="test",
            source_component="readiness-test",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=lambda _exercise, _run: "stopped",
        event_sink=lambda _event: None,
        clock=lambda: NOW,
    )
    action_request = make_action_request(
        exercise_id="silent-spider",
        run_id="run-test-001",
        actor=entity("operator", "operator-01", role="technical_operator"),
        action_id="exercise.readiness.validate",
        target=entity("exercise_run", "run-test-001"),
        idempotency_key="readiness-test",
        dry_run=False,
        timeout_seconds=10,
        clock=lambda: NOW,
    )
    result = adapter.execute(action_request)
    assert result["status"] == "failed"
    assert result["error_code"] == "baseline_mismatch"
    assert result["message"] == "Synthetic baseline differs"
