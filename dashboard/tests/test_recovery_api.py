"""Default-preview recovery, role separation and final brief HTTP contract."""

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.impact import FULL_SCENARIO_PATH

STAFF = "recovery-facilitator-at-least-24-characters"
RECOVERY = "recovery-responder-at-least-24-characters"
SOC = "recovery-analyst-at-least-24-characters"
FIXTURE = "FILE01-disposable-fixture"


def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def portal(tmp_path):
    root = tmp_path / "disposable"
    root.mkdir()
    store = PortalStore()
    service = PortalService(
        store, run_id="recovery-api-run", scenario_path=FULL_SCENARIO_PATH, impact_root=root,
    )
    auth = TokenAuthenticator({
        STAFF: PortalPrincipal("facilitator", "facilitator"),
        RECOVERY: PortalPrincipal("recovery-learner", "cloud_responder"),
        SOC: PortalPrincipal("analyst", "soc_analyst"),
    })
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


def advance(client, seconds):
    response = client.post(
        "/api/facilitator/advance", headers=headers(STAFF), json={"elapsed_seconds": seconds},
    )
    assert response.status_code == 200


def stage(client):
    for command in ("prepare", "start"):
        assert client.post(f"/api/facilitator/{command}", headers=headers(STAFF)).status_code == 200
    client.post("/api/participant/checkpoints/dp1", headers=headers(SOC), json={
        "affected_identity": "sarah", "classification": "account compromise",
        "evidence": [
            {"reference_id": "HD-1042", "source": "helpdesk"},
            {"reference_id": "factor-red-01", "source": "identity"},
            {"reference_id": "sess-red-01", "source": "identity"},
        ],
    })
    advance(client, 3600)
    assert client.post("/api/facilitator/checkpoints/dp2", headers=headers(STAFF)).status_code == 200
    advance(client, 5700)
    assert client.post("/api/facilitator/checkpoints/dp3", headers=headers(STAFF)).status_code == 200
    advance(client, 6600)
    response = client.post("/api/facilitator/checkpoints/dp4", headers=headers(STAFF))
    assert response.status_code == 200
    assert response.json()["evaluation"]["passed"] is False


def action(client, action_id="recovery.fixture.restore", *, token=RECOVERY, **overrides):
    payload = {"action_id": action_id, "fixture_id": FIXTURE, "key": action_id}
    payload.update(overrides)
    return client.post("/api/participant/recovery/action", headers=headers(token), json=payload)


def payload(service):
    return {
        "confirmed_scope": "Synthetic identities and the mock export.",
        "confirmed_cloud_records": 25,
        "business_impact": "Decoy export unavailable during the exercise.",
        "actions_taken": "Restored the supplied fixture and validated hashes.",
        "remaining_risk": "External transfer not proven.",
        "recommendations": ["Review helpdesk verification.", "Restrict service-key permissions."],
        "evidence_ids": [service.run.impact.validation_event_id],
    }


def restore_and_validate(client):
    assert action(client, dry_run=False).status_code == 200
    assert action(client, "recovery.health.validate", dry_run=False).status_code == 200


def test_recovery_read_api_is_role_safe_and_never_exposes_server_paths(portal):
    client, service = portal
    assert client.get("/api/participant/recovery").status_code == 401
    assert client.get("/api/participant/recovery", headers=headers(STAFF)).status_code == 403
    stage(client)
    response = client.get("/api/participant/recovery", headers=headers(SOC))
    assert response.status_code == 200
    assert response.json()["fixture"]["available_originals"] == 0
    assert response.json()["fixture"]["originals_unchanged"]
    assert str(service.run.impact.root) not in response.text
    assert "dp4_preview" not in response.text and "recovery_preview" not in response.text


def test_omitted_dry_run_defaults_to_preview(portal):
    client, service = portal
    stage(client)
    before = service.run.impact.fixture.inspect()
    response = action(client)
    assert response.status_code == 200
    assert response.json()["status"] == "dry_run"
    assert service.run.impact.fixture.inspect() == before
    assert service.run.impact.validation_event_id is None


def test_explicit_restore_health_and_brief_are_correlated_and_receipt_only(portal):
    client, service = portal
    stage(client)
    restore_and_validate(client)
    response = client.post(
        "/api/participant/recovery/brief", headers=headers(SOC), json=payload(service),
    )
    assert response.status_code == 200
    assert set(response.json()) == {"submission_id", "status", "run_id"}
    record = service.store.submissions(service.run.run_id)[-1]
    assert record["actor_id"] == "analyst" and record["submission_type"] == "recovery_brief"
    assert record["result"] == {"status": "submitted"}
    advance(client, 7800)
    assert service.run.controller.state.value == "completed"
    assert service.run.impact.final_review.passed
    assert action(client, dry_run=False, key="after-completion").status_code == 403


def test_readonly_analyst_cannot_restore_or_forge_recovery_role(portal):
    client, service = portal
    stage(client)
    assert action(client, token=SOC, dry_run=False).status_code == 403
    forged = action(client, token=SOC, dry_run=False, actor={"role": "cloud_responder"})
    assert forged.status_code == 422
    assert service.run.impact.fixture.inspect()["available_originals"] == 0
    assert client.post("/api/facilitator/checkpoints/dp4", headers=headers(RECOVERY)).status_code == 403
    assert client.post("/api/facilitator/impact/rollback", headers=headers(RECOVERY)).status_code == 403


@pytest.mark.parametrize("overrides", [
    {"path": "/outside"},
    {"parameters": {"variant": "realized"}},
    {"action_id": "impact.marker.apply"},
    {"fixture_id": ""},
    {"dry_run": None},
    {"dry_run": "false"},
])
def test_invalid_recovery_fields_cannot_expand_filesystem_scope(portal, overrides):
    client, service = portal
    stage(client)
    before = service.run.impact.fixture.inspect()
    assert action(client, **overrides).status_code == 422
    assert service.run.impact.fixture.inspect() == before


def test_exact_target_boundary_and_validation_before_restore(portal):
    client, service = portal
    stage(client)
    bad = action(client, fixture_id="/outside", dry_run=False)
    assert bad.status_code == 403
    assert bad.json()["detail"]["error_code"] == "target_denied"
    unhealthy = action(client, "recovery.health.validate", dry_run=False)
    assert unhealthy.status_code == 403
    assert service.run.impact.validation_event_id is None


@pytest.mark.parametrize("overrides", [
    {"confirmed_cloud_records": 26}, {"confirmed_cloud_records": True},
    {"confirmed_scope": " "}, {"remaining_risk": ""},
    {"recommendations": ["Only one"]}, {"recommendations": [" ", "second"]},
    {"evidence_ids": []}, {"evidence_ids": ["x" * 129]},
    {"controller_result": "pass"},
])
def test_final_brief_contract_rejects_incomplete_or_forged_fields(portal, overrides):
    client, service = portal
    stage(client)
    restore_and_validate(client)
    report = payload(service)
    report.update(overrides)
    response = client.post("/api/participant/recovery/brief", headers=headers(SOC), json=report)
    assert response.status_code == 422
    assert service.run.impact.brief is None


def test_fake_evidence_does_not_receive_an_answer_or_score(portal):
    client, service = portal
    stage(client)
    restore_and_validate(client)
    report = payload(service)
    report["evidence_ids"] = ["unrelated-or-previous-run-event"]
    response = client.post("/api/participant/recovery/brief", headers=headers(SOC), json=report)
    assert response.status_code == 409
    assert service.run.impact.brief is None


def test_stop_reset_restores_old_fixture_and_retains_archived_evidence(portal):
    client, service = portal
    stage(client)
    old_fixture = service.run.impact.fixture
    response = client.post(
        "/api/facilitator/stop", headers=headers(STAFF), json={"reason": "recovery drill"},
    )
    assert response.status_code == 200
    assert action(client, dry_run=False, key="after-stop").status_code == 403
    reset = client.post(
        "/api/facilitator/reset", headers=headers(STAFF), json={"new_run_id": "recovery-api-new"},
    )
    assert reset.status_code == 200
    assert reset.json()["reset"]["impact_baseline_verified"]
    assert old_fixture.inspect()["baseline_verified"]
    assert service.run.impact.fixture.inspect()["baseline_verified"]
    assert service.store.events(service.run.definition.exercise_id, "recovery-api-run")


def test_staff_rollback_is_one_use_and_clears_validation(portal):
    client, service = portal
    stage(client)
    response = client.post("/api/facilitator/impact/rollback", headers=headers(STAFF))
    assert response.status_code == 200
    assert service.run.impact.fixture.inspect()["baseline_verified"]
    assert service.run.impact.validation_event_id is None
    assert client.post("/api/facilitator/impact/rollback", headers=headers(STAFF)).status_code == 409


def test_unsafe_fixture_does_not_disable_emergency_stop(portal, tmp_path):
    client, service = portal
    outside = tmp_path / "outside"
    outside.write_bytes(b"never modify outside")
    fixture = service.run.impact.fixture
    path = fixture.live_dir / "billing-export.csv"
    path.unlink()
    path.symlink_to(outside)
    assert client.get("/api/participant/recovery", headers=headers(SOC)).status_code == 409
    stopped = client.post(
        "/api/facilitator/stop", headers=headers(STAFF), json={"reason": "unsafe fixture"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["impact"]["health_error"] == "unsafe_or_unreadable_fixture"
    reset = client.post(
        "/api/facilitator/reset", headers=headers(STAFF), json={"new_run_id": "denied-reset"},
    )
    assert reset.status_code == 409
    assert outside.read_bytes() == b"never modify outside"


def test_browser_forms_do_not_embed_answer_identifiers_or_external_dependencies(portal):
    client, _service = portal
    page = client.get("/participant")
    assert "Disposable-file recovery" in page.text
    assert "Preview only" in page.text and 'id="recovery-preview" type="checkbox" checked' in page.text
    for identifier in ("FILE01-disposable-fixture", "impact-task-01", "svc-print-sync"):
        assert identifier not in page.text
    assert "https://" not in page.text
    assert "textContent" in client.get("/static/participant.js").text
