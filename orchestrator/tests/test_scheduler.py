"""Real-time scenario scheduler tests using a deterministic monotonic clock."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.controller import AutomationResult, RunState, ScenarioController
from orchestrator.scenario import load_scenario
from orchestrator.scheduler import ScenarioScheduler


SCENARIO_PATH = (
    Path(__file__).resolve().parents[1] / "scenarios" / "identity-slice.v1.json"
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def _scheduler():
    events = []
    scenario = load_scenario(SCENARIO_PATH)

    def handler(_item, _run_id):
        return AutomationResult(True, "completed")

    handlers = {
        item.action_id: handler for item in scenario.items if item.action_id
    }
    controller = ScenarioController(
        scenario,
        event_sink=events.append,
        handlers=handlers,
        run_id="run-scheduler-test",
    )
    clock = Clock()
    return ScenarioScheduler(controller, monotonic=clock), controller, clock


def test_scheduler_advances_only_complete_monotonic_seconds() -> None:
    scheduler, controller, clock = _scheduler()
    scheduler.start()

    clock.value += 4.6
    assert scheduler.tick() == 4
    clock.value += 0.6
    assert scheduler.tick() == 5
    assert controller.elapsed_seconds == 5


def test_pause_time_is_not_counted_after_resume() -> None:
    scheduler, controller, clock = _scheduler()
    scheduler.start()
    clock.value += 10
    scheduler.pause()
    assert controller.state == RunState.PAUSED
    assert controller.elapsed_seconds == 10

    clock.value += 300
    assert scheduler.tick() == 10
    scheduler.resume()
    clock.value += 5
    assert scheduler.tick() == 15


def test_manual_advance_reanchors_real_time() -> None:
    scheduler, controller, clock = _scheduler()
    scheduler.start()
    clock.value += 2
    scheduler.advance_to(900)
    assert controller.elapsed_seconds == 900

    clock.value += 3
    assert scheduler.tick() == 903


def test_scheduler_rejects_backwards_monotonic_clock() -> None:
    scheduler, _controller, clock = _scheduler()
    scheduler.start()
    clock.value -= 1

    with pytest.raises(RuntimeError, match="backwards"):
        scheduler.tick()
