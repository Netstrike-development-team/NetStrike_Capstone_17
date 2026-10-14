"""Fail-closed pre-play readiness, read-only inspection and staff audit boundary."""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.controller import (
    AutomationResult,
    ControllerError,
    ItemStatus,
    RunState,
)
from orchestrator.impact import FULL_SCENARIO_PATH
from orchestrator.cloud import CLOUD_SCENARIO_PATH

STAFF = PortalPrincipal("staff-alice", "facilitator")
TECH = PortalPrincipal("staff-bob", "technical_operator")
TOKENS = {
    "facilitator": "readiness-facilitator-at-least-24-characters",
    "technical_operator": "readiness-operator-at-least-24-characters",
    "soc_analyst": "readiness-analyst-at-least-24-characters",
    "evaluator": "readiness-evaluator-at-least-24-characters",
    "simulated_user": "readiness-user-at-least-24-characters",
    "identity_capture_service": "readiness-capture-at-least-24-characters",
}


def headers(role="facilitator"):
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "disposable"
    root.mkdir()
    store = PortalStore()
    instance = PortalService(
        store,
        run_id="readiness-run",
        scenario_path=FULL_SCENARIO_PATH,
        impact_root=root,
    )
    yield instance
    store.close()


@pytest.fixture
def portal(service):
    auth = TokenAuthenticator(
        {
            token: PortalPrincipal("actor-" + role, role)
            for role, token in TOKENS.items()
        }
    )
    with TestClient(
        create_app(service, auth, sso_allowed_origins={"http://testserver"})
    ) as client:
        yield client, service


def events(service):
    return service.store.events(service.run.definition.exercise_id, service.run.run_id)


def test_report_is_inert_staff_only_and_never_claims_range_readiness(
    portal, monkeypatch
):
    client, service = portal
    before = events(service)
    original = Path.open

    def read_only(self, mode="r", *args, **kwargs):
        assert not any(value in mode for value in "wax+")
        return original(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only)
    response = client.get("/api/facilitator/readiness", headers=headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    report = response.json()
    assert report["ready_to_prepare"] and not report["ready_to_start"]
    assert not report["preparation_complete"] and report["blockers"] == []
    assert report["scope"] == "local_application_only"
    assert report["external_readiness_verified"] is False
    assert all(item["status"] == "not_checked" for item in report["external_checks"])
    assert str(service.run.impact.root) not in response.text
    assert events(service) == before and service.run.sequencer.sequence == 0


@pytest.mark.parametrize("role", list(TOKENS))
def test_role_boundary_for_readiness_and_prepare_start(portal, role):
    client, _ = portal
    expected = 200 if role in {"facilitator", "technical_operator"} else 403
    assert (
        client.get("/api/facilitator/readiness", headers=headers(role)).status_code
        == expected
    )
    if expected == 403:
        for operation in ("prepare", "start"):
            assert (
                client.post(
                    f"/api/facilitator/{operation}", headers=headers(role)
                ).status_code
                == 403
            )
    assert client.get("/api/facilitator/readiness").status_code == 401


@pytest.mark.parametrize("principal", [STAFF, TECH])
def test_prepare_then_start_is_audited_and_knows_the_intentional_armed_task(
    service, principal
):
    service.prepare_run(principal)
    assert service.readiness()["ready_to_start"]
    assert service.run.endpoint_state.processes["impact-task-01"]["active"] is True
    service.start_run(principal)
    assert service.run.controller.state == RunState.RUNNING
    audits = [
        event
        for event in events(service)
        if event["event_type"] == "exercise.readiness.checked"
    ]
    assert [item["data"]["operation"] for item in audits] == [
        "prepare",
        "start",
        "start",
    ]
    assert all(event["actor"]["id"] == principal.actor_id for event in audits)
    assert all(event["actor"]["role"] == principal.role for event in audits)
    assert all(event["visibility"] == "facilitator" for event in audits)
    assert [event["sequence"] for event in events(service)] == list(
        range(1, len(events(service)) + 1)
    )


@pytest.mark.parametrize("scenario", [None, CLOUD_SCENARIO_PATH, FULL_SCENARIO_PATH])
def test_start_only_clients_prepare_safely_for_all_scenario_variants(
    tmp_path, scenario
):
    root = tmp_path / "disposable"
    root.mkdir()
    store = PortalStore()
    instance = PortalService(
        store, run_id="ready-variant", scenario_path=scenario, impact_root=root
    )
    try:
        state = instance.start_run(STAFF)
        assert state["controller"]["state"] == "running"
        assert instance.run.automation.state.history_staged
        assert all(
            instance.run.controller.items[item.item_id].status == ItemStatus.DELIVERED
            for item in instance.run.definition.items
            if item.trigger.trigger_type == "pre_exercise"
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "fault,blocker",
    [
        ("identity", "identity_baseline"),
        ("endpoint", "endpoint_baseline"),
        ("cloud", "cloud_baseline"),
        ("fixture", "impact_baseline"),
        ("handler", "required_handlers"),
        ("handler_noncallable", "required_handlers"),
        ("mfa", "scheduled_mfa_baseline"),
        ("simulation", "simulation_baseline"),
        ("submission", "submissions_empty"),
        ("skipped", "preparation_progress"),
    ],
)
def test_dirty_baselines_and_missing_dependencies_block_without_running(
    portal, fault, blocker
):
    client, service = portal
    run = service.run
    if fault == "identity":
        run.identity_state.sessions["sess-red-01"]["active"] = False
    elif fault == "endpoint":
        run.endpoint_state.hosts["FIN-WS01"]["isolated"] = True
    elif fault == "cloud":
        run.cloud.state.keys["svc-cloud-backup-key-01"]["active"] = False
    elif fault == "fixture":
        (run.impact.fixture.run_root / "live" / "billing-export.csv").write_bytes(
            b"dirty"
        )
    elif fault == "handler":
        del run.controller.handlers["cloud.access.stage"]
    elif fault == "handler_noncallable":
        run.controller.handlers["cloud.access.stage"] = None
    elif fault == "mfa":
        run.mfa.pending = {"expires_at_seconds": 5}
    elif fault == "simulation":
        run.automation.state.discovery_runs = 1
    elif fault == "submission":
        service.store.save_submission(
            exercise_id=run.definition.exercise_id,
            run_id=run.run_id,
            actor_id="learner",
            submission_type="test",
            payload={},
            result={},
        )
    else:
        run.controller.skip("PRE-03", "local test")
    assert blocker in service.readiness()["blockers"]
    response = client.post("/api/facilitator/start", headers=headers())
    assert response.status_code == 409 and blocker in response.json()["detail"]
    assert run.controller.state == RunState.READY
    assert not run.automation.state.baseline_loaded
    assert not any(
        event["event_type"] == "scenario.run.started" for event in events(service)
    )
    assert events(service)[-1]["outcome"]["status"] == "blocked"


def test_rechecks_mutation_after_prepare_without_reapplying_setup(portal):
    client, service = portal
    assert client.post("/api/facilitator/prepare", headers=headers()).status_code == 200
    service.run.cloud.state.keys["svc-cloud-backup-key-01"]["active"] = False
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 409
    assert service.run.controller.state == RunState.READY
    assert service.run.cloud.state.keys["svc-cloud-backup-key-01"]["active"] is False


def test_failed_setup_is_visible_and_cannot_be_bypassed_by_start(portal):
    client, service = portal
    service.run.controller.handlers["identity.history.stage"] = (
        lambda *_: AutomationResult(False, "setup fault")
    )
    response = client.post("/api/facilitator/prepare", headers=headers())
    assert response.status_code == 409
    assert service.run.controller.items["PRE-02"].status == ItemStatus.FAILED
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 409
    assert service.run.controller.state == RunState.READY


def test_read_failure_is_safe_and_does_not_leak_paths(portal, monkeypatch):
    client, service = portal

    def unavailable():
        raise OSError("private path /private/secret and credentials must not leak")

    monkeypatch.setattr(service.run.impact.fixture, "inspect", unavailable)
    response = client.get("/api/facilitator/readiness", headers=headers())
    assert response.status_code == 200
    assert "impact_baseline" in response.json()["blockers"]
    assert "private" not in response.text and "credentials" not in response.text
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 409


def test_ledger_read_failure_blocks_without_attempting_to_audit(portal, monkeypatch):
    client, service = portal

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(service.store, "events", unavailable)
    response = client.post("/api/facilitator/start", headers=headers())
    assert response.status_code == 409 and "event_ledger" in response.json()["detail"]
    assert service.run.sequencer.sequence == 0
    assert service.run.controller.state == RunState.READY


def test_audit_write_failure_blocks_before_setup_and_never_claims_start(
    portal, monkeypatch
):
    client, service = portal

    def unavailable(_event):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(service.store, "append_event", unavailable)
    response = client.post("/api/facilitator/start", headers=headers())
    assert (
        response.status_code == 409 and "audit unavailable" in response.json()["detail"]
    )
    assert "private" not in response.text
    assert service.run.controller.state == RunState.READY
    assert not service.run.automation.state.baseline_loaded
    assert "event_ledger" in service.readiness()["blockers"]


def test_reused_persisted_run_id_cannot_start_or_overwrite_evidence(tmp_path):
    store = PortalStore(tmp_path / "ledger.sqlite3")
    first = PortalService(store, run_id="persisted-run")
    first.prepare_run(STAFF)
    before = events(first)
    second = PortalService(store, run_id="persisted-run")
    try:
        assert "event_ledger" in second.readiness()["blockers"]
        with pytest.raises(ControllerError, match="event_ledger"):
            second.start_run(STAFF)
        assert events(second) == before
        assert second.run.controller.state == RunState.READY
    finally:
        store.close()


def test_stop_and_reset_restore_a_startable_application(service):
    service.start_run(STAFF)
    service.run.fail_safe_stop("local readiness test")
    assert not service.readiness()["ready_to_prepare"]
    service.reset_run(new_run_id="readiness-next")
    assert service.readiness()["ready_to_prepare"]
    service.start_run(STAFF)
    assert service.run.controller.state == RunState.RUNNING


def test_readiness_audits_and_blockers_never_reach_participant_signals(service):
    service.prepare_run(STAFF)
    report = service.participant_evidence(PortalPrincipal("analyst", "soc_analyst"))
    serialized = json.dumps(report)
    assert "exercise.readiness.checked" not in serialized
    assert "ready_to_start" not in serialized and "blockers" not in serialized


def test_nonstaff_direct_service_controls_are_denied_before_any_events(service):
    with pytest.raises(ControllerError, match="exercise-control role"):
        service.start_run(PortalPrincipal("learner", "soc_analyst"))
    assert not events(service)


@pytest.mark.parametrize("fault", ["symlink", "extra_file", "staging"])
def test_unsafe_disposable_inventory_is_blocked_without_touching_external_files(
    service, tmp_path, fault
):
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"preserve unrelated user data")
    root = service.run.impact.fixture.run_root
    if fault == "symlink":
        path = root / "live" / "billing-export.csv"
        path.rename(tmp_path / "original.csv")
        path.symlink_to(outside)
    elif fault == "extra_file":
        (root / "live" / "unexpected.txt").write_text("unexpected")
    else:
        (root / "staging" / "unexpected.txt").write_text("unexpected")
    assert "impact_baseline" in service.readiness()["blockers"]
    with pytest.raises(ControllerError, match="impact_baseline"):
        service.start_run(STAFF)
    assert outside.read_bytes() == b"preserve unrelated user data"


def test_repeated_prepare_does_not_duplicate_setup_or_rearm_changed_task(service):
    service.prepare_run(STAFF)
    service.prepare_run(STAFF)
    setup_events = [
        event
        for event in events(service)
        if event["event_type"] == "scenario.item.delivered"
        and event["target"]["id"].startswith("PRE-")
    ]
    assert len(setup_events) == 3
    service.run.endpoint_state.processes["impact-task-01"]["active"] = False
    with pytest.raises(ControllerError, match="endpoint_baseline"):
        service.prepare_run(STAFF)
    assert service.run.endpoint_state.processes["impact-task-01"]["active"] is False


def test_preplay_sign_in_must_be_reset_before_delivery(portal):
    client, service = portal
    response = client.post(
        "/api/sso/sign-in",
        headers={"Origin": "http://testserver"},
        json={"username": "sarah@simcorp.test", "credential": "exercise-only-value"},
    )
    assert response.status_code == 200
    blockers = service.readiness()["blockers"]
    assert "sso_baseline" in blockers and "identity_audit_empty" in blockers
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 409
    assert (
        client.post(
            "/api/facilitator/stop",
            headers=headers(),
            json={"reason": "pre-play demo complete"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/facilitator/reset",
            headers=headers(),
            json={"new_run_id": "fresh-delivery"},
        ).status_code
        == 200
    )
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200


def test_identity_capture_cannot_interleave_with_guarded_start(service, monkeypatch):
    preparing = threading.Event()
    release = threading.Event()
    capturing = threading.Event()
    original = service.run.controller.prepare

    def paused_prepare():
        preparing.set()
        assert release.wait(5)
        original()

    def capture():
        capturing.set()
        return service.capture_identity_interaction(
            "simcorp-sso",
            {
                "phase": "identity",
                "synthetic_identity": "sarah",
                "action": "identity.sign_in.attempt",
                "result": "success",
                "source_event_id": "concurrent-capture",
            },
        )

    monkeypatch.setattr(service.run.controller, "prepare", paused_prepare)
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(service.start_run, STAFF)
        try:
            assert preparing.wait(5)
            captured = pool.submit(capture)
            assert capturing.wait(5)
            assert not captured.done()
        finally:
            release.set()
        assert started.result(timeout=5)["controller"]["state"] == "running"
        captured.result(timeout=5)
    ledger = events(service)
    start_sequence = next(
        event["sequence"]
        for event in ledger
        if event["event_type"] == "scenario.run.started"
    )
    capture_sequence = next(
        event["sequence"]
        for event in ledger
        if event["event_type"] == "identity.interaction.recorded"
    )
    assert capture_sequence > start_sequence
