"""Deterministic scenario-controller behavior and safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.controller import (
    AutomationResult,
    ControllerError,
    ItemStatus,
    RunState,
    ScenarioController,
)
from orchestrator.scenario import load_scenario
from shared.events import EventValidator


SCENARIO_PATH = (
    Path(__file__).resolve().parents[1] / "scenarios" / "identity-slice.v1.json"
)


def _controller(*, failing_action: str | None = None):
    scenario = load_scenario(SCENARIO_PATH)
    events = []
    calls = []

    def handler(item, run_id):
        calls.append((item.action_id, run_id))
        if item.action_id == failing_action:
            return AutomationResult(False, "fixture unavailable", {"fallback": True})
        return AutomationResult(True, f"Completed {item.item_id}", {"safe": True})

    handlers = {
        item.action_id: handler for item in scenario.items if item.action_id is not None
    }
    return (
        ScenarioController(
            scenario,
            event_sink=events.append,
            handlers=handlers,
            run_id="run-controller-test",
        ),
        events,
        calls,
    )


def test_preparation_and_timed_delivery_are_deterministic() -> None:
    controller, events, calls = _controller()

    controller.prepare()
    controller.start()
    controller.advance_to(900)

    assert controller.items["PRE-01"].status == ItemStatus.DELIVERED
    assert controller.items["PRE-02"].status == ItemStatus.DELIVERED
    assert controller.items["MSEL-01"].status == ItemStatus.DELIVERED
    assert controller.items["MSEL-02"].status == ItemStatus.DELIVERED
    assert controller.items["ACT-01"].status == ItemStatus.DELIVERED
    assert [call[0] for call in calls] == [
        "scenario.baseline.load",
        "identity.history.stage",
        "identity.mfa.challenge.deliver",
        "identity.mfa.challenge.deliver",
        "identity.mfa.challenge.deliver",
        "identity.session.replay",
    ]
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    validator = EventValidator()
    for event in events:
        validator.validate(event)


def test_pause_blocks_time_advance_but_manual_delivery_remains_available() -> None:
    controller, _, _ = _controller()
    controller.start()
    controller.advance_to(1500)
    assert controller.items["MSEL-03"].status == ItemStatus.READY

    controller.pause()
    with pytest.raises(ControllerError, match="requires state running"):
        controller.advance_to(2400)
    controller.deliver("MSEL-03")
    assert controller.items["MSEL-03"].status == ItemStatus.DELIVERED

    controller.resume()
    controller.advance_to(2400)
    assert controller.items["DP1"].status == ItemStatus.READY


def test_failed_automatic_action_is_visible_and_not_retried_silently() -> None:
    controller, events, calls = _controller(failing_action="identity.session.replay")
    controller.start()
    controller.advance_to(900)
    controller.advance_to(1000)

    runtime = controller.items["ACT-01"]
    assert runtime.status == ItemStatus.FAILED
    assert runtime.error == "fixture unavailable"
    assert sum(call[0] == "identity.session.replay" for call in calls) == 1
    failure = next(event for event in events if event["event_type"] == "scenario.item.failed")
    assert failure["outcome"]["status"] == "error"
    assert failure["data"]["fallback"] is True


def test_missing_handler_fails_closed() -> None:
    scenario = load_scenario(SCENARIO_PATH)
    events = []
    controller = ScenarioController(
        scenario, event_sink=events.append, run_id="run-no-handlers"
    )

    controller.prepare()

    assert controller.items["PRE-01"].status == ItemStatus.FAILED
    assert "no allowlisted handler" in controller.items["PRE-01"].error


def test_handler_exception_type_is_visible_without_leaking_detail() -> None:
    scenario = load_scenario(SCENARIO_PATH)
    events = []

    def unsafe_handler(_item, _run_id):
        raise RuntimeError("secret-value-must-not-enter-the-ledger")

    controller = ScenarioController(
        scenario,
        event_sink=events.append,
        handlers={"scenario.baseline.load": unsafe_handler},
        run_id="run-handler-error",
    )

    controller.prepare()

    assert controller.items["PRE-01"].error == "handler raised RuntimeError"
    assert "secret-value" not in str(events)


@pytest.mark.parametrize(
    ("passed", "selected", "skipped"),
    [(True, "ACT-04A", "ACT-04B"), (False, "ACT-04B", "ACT-04A")],
)
def test_dp2_result_selects_exactly_one_branch(passed, selected, skipped) -> None:
    controller, events, _ = _controller()
    controller.start()
    controller.advance_to(5100)

    controller.resolve_checkpoint(
        "DP2",
        passed=passed,
        evidence_ids=("session-state", "factor-state", "endpoint-state"),
        reason="Verifier results recorded",
    )

    assert controller.checkpoint_results["DP2"] == ("pass" if passed else "miss")
    assert controller.items[selected].status == ItemStatus.DELIVERED
    assert controller.items[skipped].status == ItemStatus.SKIPPED
    result_event = next(
        event
        for event in events
        if event["event_type"] == "scenario.checkpoint.resolved"
    )
    assert result_event["data"]["evidence_ids"] == [
        "session-state",
        "factor-state",
        "endpoint-state",
    ]


def test_fail_safe_stop_prevents_future_delivery_and_reset_starts_new_run() -> None:
    controller, events, _ = _controller()
    controller.start()
    controller.fail_safe_stop("required telemetry unavailable")

    with pytest.raises(ControllerError):
        controller.advance_to(900)
    controller.reset(new_run_id="run-after-reset")

    assert controller.state == RunState.READY
    assert controller.run_id == "run-after-reset"
    assert controller.elapsed_seconds == 0
    assert all(runtime.status == ItemStatus.PENDING for runtime in controller.items.values())
    assert events[-1]["data"]["previous_run_id"] == "run-controller-test"


def test_snapshot_is_json_compatible_and_exposes_facilitator_state() -> None:
    controller, _, _ = _controller()
    controller.start()
    controller.advance_to(1500)

    snapshot = controller.snapshot()

    assert snapshot["state"] == "running"
    assert snapshot["elapsed_seconds"] == 1500
    assert snapshot["items"]["MSEL-03"]["status"] == "ready"
