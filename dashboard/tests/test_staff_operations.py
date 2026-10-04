"""Current-run staff controls, consistent diagnostics and reset serialization."""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dashboard.service import PortalService
from dashboard.store import PortalStore
from dashboard.tests.test_archives import app, headers, STAFF


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id="staff-current")
    # Lifespan provides supervised health; detailed timing faults are tested separately.
    with TestClient(app(service)) as client:
        yield client, service
    store.close()


CONTROLS = [
    ("prepare", None), ("start", None), ("pause", None), ("resume", None),
    ("advance", {"elapsed_seconds": 60}), ("deliver", {"item_id": "MSEL-01"}),
    ("skip", {"item_id": "MSEL-01", "reason": "staff test"}),
    ("checkpoints/dp2", None), ("checkpoints/dp3", None), ("checkpoints/dp4", None),
    ("stop", {"reason": "staff safety"}), ("reset", {"new_run_id": "staff-next"}),
    ("impact/rollback", None),
    ("mfa/decision", {"challenge_id": "pending", "decision": "deny"}),
]


@pytest.mark.parametrize("action,payload", CONTROLS)
def test_stale_controls_rejected_before_mutation(portal, action, payload):
    client, service = portal
    before = service.facilitator_state()
    response = client.post(f"/api/facilitator/{action}", json=payload,
                           headers={**headers(), "X-Exercise-Run-ID": "old-private-run"})
    assert response.status_code == 409
    assert "old-private-run" not in response.text
    after = service.facilitator_state()
    for key in ("controller", "events", "submissions", "sso", "scheduled_mfa"):
        assert after[key] == before[key]


@pytest.mark.parametrize("value", ["", " bad ", "x" * 129, "bad\tvalue"])
def test_invalid_run_header_is_generic_and_nonmutating(portal, value):
    client, service = portal
    response = client.post("/api/facilitator/start", headers={**headers(), "X-Exercise-Run-ID": value})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid exercise run header"
    assert service.run.controller.state.value == "ready"


def test_duplicate_run_header_is_rejected(portal):
    client, _ = portal
    auth = list(headers().items())
    response = client.post("/api/facilitator/start", headers=auth + [
        ("X-Exercise-Run-ID", "staff-current"), ("X-Exercise-Run-ID", "staff-current")])
    assert response.status_code == 422
    assert response.json()["detail"] == "ambiguous exercise run header"


@pytest.mark.parametrize("role", ["soc_analyst", "evaluator", "simulated_user", "identity_capture_service"])
def test_run_header_does_not_grant_staff_authority(portal, role):
    client, _ = portal
    assert client.post("/api/facilitator/start", headers={**headers(role),
        "X-Exercise-Run-ID": "staff-current"}).status_code == 403


def test_legacy_header_omission_and_scoped_technical_controls_work(portal):
    client, _ = portal
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    assert client.post("/api/facilitator/pause", headers={**headers("technical_operator"),
        "X-Exercise-Run-ID": "staff-current"}).status_code == 200
    assert client.post("/api/facilitator/mfa/decision", headers={**headers("technical_operator"),
        "X-Exercise-Run-ID": "staff-current"}, json={"challenge_id": "pending", "decision": "deny"}).status_code == 403


@pytest.mark.parametrize("format_name", ["jsonl", "csv"])
def test_staff_exports_pin_run_and_preserve_cache_boundary(portal, format_name):
    client, service = portal
    service.start_run(STAFF)
    path = f"/api/facilitator/exports/events.{format_name}"
    assert client.get(path, headers={**headers(), "X-Exercise-Run-ID": "old"}).status_code == 409
    response = client.get(path, headers={**headers(), "X-Exercise-Run-ID": "staff-current"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f"staff-current-events.{format_name}" in response.headers["content-disposition"]
    if format_name == "jsonl":
        assert all(json.loads(line)["run_id"] == "staff-current" for line in response.text.splitlines())


def test_state_is_authorized_consistent_and_read_only(portal):
    client, service = portal
    before = service.store.events(service.run.definition.exercise_id, service.run.run_id)
    for role in ("facilitator", "technical_operator"):
        response = client.get("/api/facilitator/state", headers=headers(role))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        state = response.json()
        assert state["principal_role"] == role
        assert state["controller"]["run_id"] == state["clock"]["run_id"] == state["readiness"]["run_id"]
        assert state["readiness"]["external_readiness_verified"] is False
    assert service.store.events(service.run.definition.exercise_id, service.run.run_id) == before
    assert client.get("/api/facilitator/state", headers=headers("soc_analyst")).status_code == 403


def test_fault_reset_response_contains_fresh_readiness_and_archive_receipt(portal):
    client, service = portal
    service.start_run(STAFF)
    service.clock.fault("driver_failed")
    response = client.post("/api/facilitator/reset", headers={**headers(),
        "X-Exercise-Run-ID": "staff-current"}, json={"new_run_id": "staff-next"})
    assert response.status_code == 200
    state = response.json()
    assert state["clock"]["fault_code"] is None
    assert state["clock"]["run_id"] == state["readiness"]["run_id"] == "staff-next"
    assert state["readiness"]["ready_to_prepare"] is True
    assert state["reset"]["prior_run_id"] == "staff-current"
    assert state["reset"]["review_archive_id"]
    assert client.post("/api/facilitator/start", headers={**headers(),
        "X-Exercise-Run-ID": "staff-current"}).status_code == 409
    assert service.run.controller.state.value == "ready"


def test_control_holds_scope_lock_until_result_and_reset_waits(portal, monkeypatch):
    client, service = portal
    service.start_run(STAFF)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    stop = service.stop_run

    def hold_stop(reason, principal):
        result = stop(reason, principal)
        entered.set()
        assert release.wait(5)
        assert service.run.run_id == "staff-current"
        return result

    def reset():
        attempted.set()
        return client.post("/api/facilitator/reset", headers={**headers(),
            "X-Exercise-Run-ID": "staff-current"}, json={"new_run_id": "staff-next"})

    monkeypatch.setattr(service, "stop_run", hold_stop)
    with ThreadPoolExecutor(max_workers=2) as pool:
        stopping = pool.submit(client.post, "/api/facilitator/stop", headers={**headers(),
            "X-Exercise-Run-ID": "staff-current"}, json={"reason": "safety"})
        try:
            assert entered.wait(5)
            resetting = pool.submit(reset)
            assert attempted.wait(5)
            assert not resetting.done()
        finally:
            release.set()
        assert stopping.result(timeout=5).status_code == 200
        assert resetting.result(timeout=5).status_code == 200
    assert service.run.run_id == "staff-next"


@pytest.mark.parametrize("path,required", [
    ("/facilitator", {"local-readiness", "clock-health", "stop", "reset"}),
    ("/evaluator", {"archive-summary", "archive-capture", "archive-next", "saved-review"}),
])
def test_offline_pages_have_unique_operations_targets(portal, path, required):
    client, _ = portal
    html = client.get(path).text
    identifiers = re.findall(r'\bid="([^"]+)"', html)
    assert len(identifiers) == len(set(identifiers))
    assert required <= set(identifiers)
    assert not re.search(r'(?:src|href)="https?://', html)
    for asset in ("staff-operations.js", "review-archives.js"):
        assert client.get(f"/static/{asset}").status_code == 200
