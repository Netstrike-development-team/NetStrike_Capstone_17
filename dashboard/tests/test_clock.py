"""Clock supervision, private diagnostics and the common runtime mutation boundary."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.controller import AutomationResult, ControllerError, RunState
from orchestrator.impact import FULL_SCENARIO_PATH
from shared.events import EventValidator

STAFF = PortalPrincipal("clock-test-staff", "facilitator")
ROLES = ("facilitator", "technical_operator", "evaluator", "soc_analyst",
         "simulated_user", "identity_capture_service")
TOKENS = {role: "clock-test-" + role + "-at-least-24-characters" for role in ROLES}


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


@pytest.fixture
def runtime():
    clock = Clock()
    store = PortalStore()
    service = PortalService(store, run_id="clock-run", monotonic=clock)
    yield service, clock
    store.close()


def app_for(service):
    auth = TokenAuthenticator({token: PortalPrincipal("actor-" + role, role)
                               for role, token in TOKENS.items()})
    return create_app(service, auth, sso_allowed_origins={"http://testserver"})


def headers(role="facilitator"):
    return {"Authorization": "Bearer " + TOKENS[role]}


def events(service, run_id=None):
    return service.store.events(service.run.definition.exercise_id, run_id or service.run.run_id)


def start(service):
    service.clock.attach()
    service.start_run(STAFF)


def test_unmanaged_cli_is_explicit_and_preserves_deterministic_controls(runtime):
    service, _ = runtime
    assert service.clock.snapshot()["status"] == "unmonitored"
    assert not service.clock.snapshot()["automatic_delivery_supervised"]
    service.start_run(STAFF)
    service.control_run("advance", 30)
    assert service.run.controller.elapsed_seconds == 30
    assert service.run.mfa.snapshot()["pending"]


def test_ticks_pause_resume_and_manual_advance_preserve_exercise_time(runtime):
    service, clock = runtime
    start(service)
    clock.value += 4.6
    service.clock.tick()
    assert service.run.controller.elapsed_seconds == 4
    clock.value += .6
    service.clock.tick()
    assert service.run.controller.elapsed_seconds == 5
    service.control_run("pause")
    for _ in range(10):
        clock.value += 20
        service.clock.tick()
    assert service.run.controller.elapsed_seconds == 5
    service.control_run("resume")
    clock.value += 5
    service.clock.tick()
    assert service.run.controller.elapsed_seconds == 10
    service.control_run("advance", 300)
    clock.value += 3
    service.clock.tick()
    assert service.run.controller.elapsed_seconds == 303
    assert service.clock.snapshot()["status"] == "healthy"


@pytest.mark.parametrize("value,code", [(131, "heartbeat_stale"), (99, "invalid_monotonic"),
                                       (float("nan"), "invalid_monotonic"),
                                       (float("inf"), "invalid_monotonic")])
def test_invalid_or_stale_time_stops_before_any_catchup(runtime, value, code):
    service, clock = runtime
    start(service)
    before = service.run.controller.elapsed_seconds
    clock.value = value
    raw = service.clock.snapshot()
    assert raw["status"] in {"stale", "invalid_clock"}
    assert service.run.controller.state == RunState.RUNNING  # GET inspection is inert.
    service.clock.tick()
    assert service.run.controller.state == RunState.STOPPED
    assert service.run.controller.elapsed_seconds == before
    assert service.clock.snapshot()["fault_code"] == code
    assert service.run.mfa.snapshot()["pending"] is None


def test_tick_failure_is_sanitized_correlated_audited_and_latched(runtime, monkeypatch):
    service, _ = runtime
    start(service)

    def broken():
        raise RuntimeError("password=do-not-publish /private/secret/path")

    monkeypatch.setattr(service.scheduler, "tick", broken)
    service.clock.tick()
    report = service.clock.snapshot()
    assert report["status"] == "faulted"
    assert report["cleanup_complete"] and report["fault_audit_persisted"]
    fault = [event for event in events(service) if event["event_type"] == "exercise.clock.faulted"]
    assert len(fault) == 1
    assert fault[0]["actor"]["type"] == "system"
    assert fault[0]["actor"]["id"] == "exercise-clock"
    assert fault[0]["source"]["component"] == "exercise-clock-supervisor"
    assert fault[0]["visibility"] == "facilitator"
    assert fault[0]["run_id"] == "clock-run"
    assert "do-not-publish" not in json.dumps(events(service)) + json.dumps(report)
    for event in events(service):
        EventValidator().validate(event)
    assert [event["sequence"] for event in events(service)] == list(range(1, len(events(service)) + 1))
    count = len(events(service))
    service.clock.tick()
    service.clock.fault("unknown-private-content")
    assert len(events(service)) == count
    assert "clock" not in service.participant_state()


@pytest.mark.parametrize("operation,args", [("resume", ()), ("advance", (300,)),
                                             ("deliver", ("MSEL-01",)), ("skip", ("MSEL-01", "test"))])
def test_faulted_clock_blocks_runtime_controls_but_not_evidence(runtime, operation, args):
    service, _ = runtime
    start(service)
    service.clock.fault("driver_failed")
    before = events(service)
    with pytest.raises(ControllerError, match="clock unavailable"):
        service.control_run(operation, *args)
    with pytest.raises(ControllerError, match="clock unavailable"):
        service.start_run(STAFF)
    assert service.aar_bundle()["run_id"] == "clock-run"
    assert events(service) == before


def test_stale_participant_action_is_rejected_before_effect(runtime, monkeypatch):
    service, clock = runtime
    start(service)
    clock.value += 31
    called = []
    monkeypatch.setattr(service.run, "submit_action", lambda **kwargs: called.append(kwargs))
    with pytest.raises(ControllerError, match="clock unavailable"):
        service.submit_action(PortalPrincipal("learner", "identity_responder"),
                              action_id="identity.account.disable", target_type="identity",
                              target_id="sarah", idempotency_key="guard")
    assert not called
    assert service.run.controller.state == RunState.STOPPED


@pytest.mark.parametrize("role", ROLES)
def test_health_is_authenticated_staff_only_pure_and_uncached(runtime, role):
    service, _ = runtime
    with TestClient(app_for(service)) as client:
        before = events(service)
        response = client.get("/api/facilitator/clock", headers=headers(role))
        assert response.status_code == (200 if role in {"facilitator", "technical_operator"} else 403)
        if response.status_code == 200:
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["status"] == "healthy"
            assert not response.json()["external_readiness_verified"]
        assert client.get("/api/facilitator/clock").status_code == 401
        assert client.get("/health").status_code == 200
        assert events(service) == before
    assert service.run.controller.state == RunState.READY
    assert service.clock.snapshot()["status"] == "detached"


def test_faulted_api_keeps_evidence_and_stop_available_then_archives_reset(runtime):
    service, clock = runtime
    with TestClient(app_for(service)) as client:
        assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
        clock.value += 31
        assert client.post("/api/facilitator/advance", headers=headers(),
                           json={"elapsed_seconds": 300}).status_code == 409
        old = events(service)
        assert client.get("/api/facilitator/state", headers=headers()).status_code == 200
        assert client.post("/api/facilitator/stop", headers=headers(),
                           json={"reason": "retain evidence"}).status_code == 200
        response = client.post("/api/facilitator/reset", headers=headers(),
                               json={"new_run_id": "clock-next-run"})
        assert response.status_code == 200
        assert response.json()["clock"]["status"] == "healthy"
        assert response.json()["clock"]["fault_code"] is None
        assert response.json()["reset"]["review_archive_id"]
        assert events(service, "clock-run")[:len(old)] == old
        assert [e["sequence"] for e in events(service)] == [1]
        assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    assert service.run.controller.state == RunState.STOPPED


def test_failed_reset_does_not_clear_fault(runtime):
    service, _ = runtime
    start(service)
    service.clock.fault("driver_failed")
    with pytest.raises(ValueError):
        service.reset_run(new_run_id="clock-run")
    assert service.clock.snapshot()["status"] == "faulted"
    assert service.run.run_id == "clock-run"


def test_all_safety_latches_attempted_even_when_audit_unavailable(runtime, monkeypatch):
    service, _ = runtime
    start(service)
    service.control_run("advance", 30)
    assert service.run.mfa.snapshot()["pending"]

    def broken(_event):
        raise OSError("private-audit-path")

    # Also replace the bound sinks captured when the runtime was constructed.
    monkeypatch.setattr(PortalStore, "append_event", lambda self, event: broken(event))
    attempted = []
    adapters = (service.run.automation.adapter, service.run.identity_adapter,
                service.run.endpoint_adapter, service.run.cloud.adapter,
                service.run.cloud.automation_adapter)
    for index, adapter in enumerate(adapters):
        original = adapter.activate_fail_safe

        def wrap(run_id, operator, reason, original=original, index=index):
            attempted.append(index)
            return original(run_id, operator, reason)

        monkeypatch.setattr(adapter, "activate_fail_safe", wrap)
        monkeypatch.setattr(adapter, "event_sink", broken)
    monkeypatch.setattr(service.run.controller, "event_sink", broken)
    monkeypatch.setattr(service.run.mfa, "sink", broken)
    service.clock.fault("scheduler_tick_failed")
    assert attempted == list(range(5))
    assert service.run.controller.state == RunState.STOPPED
    assert service.run.mfa.snapshot()["pending"] is None
    assert service.clock.snapshot()["cleanup_complete"] is False
    assert service.clock.snapshot()["fault_audit_persisted"] is False
    assert all("clock-run" in adapter._stopped_runs for adapter in adapters)
    with pytest.raises(ValueError):
        service.reset_run(new_run_id="cannot-hide-audit-gap")
    assert service.run.run_id == "clock-run"
    assert service.clock.snapshot()["status"] == "faulted"


def test_full_scenario_cleanup_includes_impact_and_preserves_decoys(tmp_path, monkeypatch):
    root = tmp_path / "decoys"
    root.mkdir()
    store = PortalStore()
    service = PortalService(store, scenario_path=FULL_SCENARIO_PATH, impact_root=root)
    try:
        start(service)
        before = service.run.impact.fixture.inspect()
        attempted = []
        for adapter in (service.run.impact.adapter, service.run.impact.automation_adapter):
            original = adapter.activate_fail_safe

            def wrap(*args, original=original):
                attempted.append(True)
                return original(*args)

            monkeypatch.setattr(adapter, "activate_fail_safe", wrap)
        service.clock.fault("driver_failed")
        assert len(attempted) == 2
        assert service.run.impact.fixture.inspect() == before
        assert service.clock.snapshot()["cleanup_complete"]
    finally:
        store.close()


def test_fault_does_not_fabricate_evaluator_judgments(runtime):
    service, _ = runtime
    start(service)
    service.clock.fault("driver_failed")
    report = service.aar_report()
    assert report["run_id"] == "clock-run"
    assert not service.store.submissions("clock-run")
    assert all(event["event_type"] != "exercise.objective.judged" for event in events(service))


def test_long_tick_fails_closed_instead_of_refreshing_away_stall(runtime, monkeypatch):
    service, clock = runtime
    start(service)
    monkeypatch.setattr(service.scheduler, "tick", lambda: setattr(clock, "value", 131))
    service.clock.tick()
    assert service.clock.snapshot()["fault_code"] == "heartbeat_stale"
    assert service.run.controller.state == RunState.STOPPED


def test_monotonic_provider_exception_is_sanitized_and_stops(runtime, monkeypatch):
    service, _ = runtime
    start(service)

    def broken():
        raise OSError("sensitive-provider-error")

    monkeypatch.setattr(service.clock, "monotonic", broken)
    assert service.clock.snapshot()["status"] == "invalid_clock"
    service.clock.tick()
    assert service.clock.snapshot()["fault_code"] == "invalid_monotonic"
    assert "sensitive-provider-error" not in json.dumps(events(service))


def test_invalid_reset_clock_does_not_clear_latch(runtime):
    service, clock = runtime
    start(service)
    service.clock.fault("driver_failed")
    clock.value = float("nan")
    with pytest.raises(ControllerError, match="valid monotonic"):
        service.clock.reset()
    assert service.clock.snapshot()["fault_code"] == "driver_failed"


def test_stop_operator_validation_precedes_effect(runtime):
    service, _ = runtime
    start(service)
    with pytest.raises(ControllerError, match="exercise-control role"):
        service.run.fail_safe_stop("unauthorized", operator={"role": "soc_analyst"})
    assert service.run.controller.state == RunState.RUNNING


def test_duplicate_driver_cannot_steal_runtime(runtime):
    service, _ = runtime
    service.clock.attach()
    with pytest.raises(ControllerError, match="already has a driver"):
        service.clock.attach()
    service.clock.detach()
    service.clock.attach()
    assert service.clock.snapshot()["status"] == "healthy"


def test_reattach_preserves_fault_until_successful_reset(runtime):
    service, _ = runtime
    start(service)
    service.clock.fault("driver_failed")
    service.clock.detach()
    service.clock.attach()
    assert service.clock.snapshot()["status"] == "faulted"
    service.reset_run(new_run_id="clock-recovered")
    assert service.clock.snapshot()["status"] == "healthy"


@pytest.mark.parametrize("state", [RunState.READY, RunState.RUNNING, RunState.PAUSED, RunState.COMPLETED])
def test_shutdown_is_stop_not_completion_and_does_not_reclassify_terminal(runtime, state):
    service, _ = runtime
    service.clock.attach()
    if state in {RunState.RUNNING, RunState.PAUSED}:
        service.start_run(STAFF)
        if state == RunState.PAUSED:
            service.control_run("pause")
    elif state == RunState.COMPLETED:
        service.run.controller.state = state
    service.clock.detach()
    expected = RunState.STOPPED if state in {RunState.RUNNING, RunState.PAUSED} else state
    assert service.run.controller.state == expected
    assert not service.clock.attached


def test_tick_and_action_share_one_mutation_boundary(runtime, monkeypatch):
    service, _ = runtime
    start(service)
    entered, release, action_entered = threading.Event(), threading.Event(), threading.Event()

    def blocking_tick():
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(service.scheduler, "tick", blocking_tick)
    monkeypatch.setattr(service.run, "submit_action", lambda **kwargs: action_entered.set())
    with ThreadPoolExecutor(max_workers=2) as pool:
        ticking = pool.submit(service.clock.tick)
        assert entered.wait(5)
        action = pool.submit(service.submit_action, STAFF, action_id="test", target_type="identity",
                             target_id="sarah", idempotency_key="lock")
        assert not action_entered.wait(.05)
        release.set()
        ticking.result(timeout=5)
        action.result(timeout=5)
    assert action_entered.is_set()


def test_inflight_tick_drains_before_reset_and_cannot_touch_new_run(runtime, monkeypatch):
    service, _ = runtime
    start(service)
    service.stop_run("reset rehearsal", STAFF)
    entered, release = threading.Event(), threading.Event()
    observed = []

    def tick():
        entered.set()
        assert release.wait(5)
        observed.append(service.run.run_id)

    monkeypatch.setattr(service.scheduler, "tick", tick)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ticking = pool.submit(service.clock.tick)
        assert entered.wait(5)
        resetting = pool.submit(service.reset_run, new_run_id="after-drained-tick")
        assert not resetting.done()
        release.set()
        ticking.result(timeout=5)
        state = resetting.result(timeout=5)
    assert observed == ["clock-run"]
    assert state["clock"]["run_id"] == "after-drained-tick"
    assert state["clock"]["successful_ticks"] == 0
    assert [e["sequence"] for e in events(service)] == [1]


def test_handler_already_stopped_controller_still_latches_every_adapter(runtime, monkeypatch):
    service, _ = runtime
    start(service)

    def broken():
        service.run.controller.fail_safe_stop("handler failure")
        raise RuntimeError("handler")

    monkeypatch.setattr(service.scheduler, "tick", broken)
    service.clock.tick()
    assert service.clock.snapshot()["cleanup_complete"]
    for adapter in (service.run.automation.adapter, service.run.identity_adapter,
                    service.run.endpoint_adapter, service.run.cloud.adapter,
                    service.run.cloud.automation_adapter):
        assert "clock-run" in adapter._stopped_runs


def test_controller_handled_failure_is_supervised_even_without_raised_tick(runtime):
    service, clock = runtime
    start(service)
    item = next(item for item in service.run.definition.items if item.item_id == "MFA-01")
    service.run.controller.handlers[item.action_id] = lambda *_: AutomationResult(False, "failed")
    clock.value += 30
    service.clock.tick()
    assert service.run.controller.state == RunState.STOPPED
    assert service.clock.snapshot()["fault_code"] == "scheduler_tick_failed"
    assert service.clock.snapshot()["cleanup_complete"]
    assert "clock-run" in service.run.identity_adapter._stopped_runs


def test_real_lifespan_driver_advances_and_drains_on_shutdown(runtime, monkeypatch):
    service, clock = runtime
    entered, release = threading.Event(), threading.Event()
    original = service.scheduler.tick

    def blocking_tick():
        entered.set()
        assert release.wait(5)
        original()

    monkeypatch.setattr(service.scheduler, "tick", blocking_tick)
    app = app_for(service)

    async def check():
        async with app.router.lifespan_context(app):
            service.start_run(STAFF)
            clock.value += 5
            assert await asyncio.to_thread(entered.wait, 5)
            # The event loop remains responsive while the synchronous tick is held.
            await asyncio.sleep(0)
            release.set()
        assert service.run.controller.elapsed_seconds == 5
        assert service.run.controller.state == RunState.STOPPED
        assert not service.clock.attached

    asyncio.run(check())


def test_cancelled_driver_drains_worker_and_faults_without_orphan_mutation(runtime, monkeypatch):
    service, clock = runtime
    entered, release = threading.Event(), threading.Event()
    original = service.scheduler.tick

    def tick():
        entered.set()
        assert release.wait(5)
        original()

    monkeypatch.setattr(service.scheduler, "tick", tick)
    app = app_for(service)

    async def check():
        with pytest.raises(asyncio.CancelledError):
            async with app.router.lifespan_context(app):
                service.start_run(STAFF)
                clock.value += 5
                assert await asyncio.to_thread(entered.wait, 5)
                driver = next(task for task in asyncio.all_tasks()
                              if task.get_name() == "netstrike-exercise-clock")
                driver.cancel()
                await asyncio.sleep(0)
                assert not driver.done()  # Cancellation cannot abandon the thread.
                release.set()
        assert service.run.controller.elapsed_seconds == 5
        assert service.run.controller.state == RunState.STOPPED
        assert service.clock.snapshot()["fault_code"] == "driver_failed"
        assert not service.clock.attached

    asyncio.run(check())
