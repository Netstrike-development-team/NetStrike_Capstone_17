"""Cloud tools are authenticated, factual, current-run scoped and offline."""

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.cloud import CLOUD_SCENARIO_PATH

STAFF = "cloud-facilitator-at-least-24-characters"
CLOUD = "cloud-responder-at-least-24-characters"
SOC = "cloud-analyst-at-least-24-characters"
ENDPOINT = "cloud-endpoint-at-least-24-characters"
BUCKET = "simcorp-customer-exports"
KEY = "svc-cloud-backup-key-01"


def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id="api-cloud-test", scenario_path=CLOUD_SCENARIO_PATH)
    auth = TokenAuthenticator({
        STAFF: PortalPrincipal("staff", "facilitator"),
        CLOUD: PortalPrincipal("cloud-responder", "cloud_responder"),
        SOC: PortalPrincipal("analyst", "soc_analyst"),
        ENDPOINT: PortalPrincipal("endpoint", "endpoint_responder"),
    })
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


def stage(client):
    for command in ("prepare", "start"):
        assert client.post(f"/api/facilitator/{command}", headers=headers(STAFF)).status_code == 200
    advance = client.post(
        "/api/facilitator/advance", headers=headers(STAFF),
        json={"elapsed_seconds": 4500},
    )
    assert advance.status_code == 200


def action(client, action_id, target_type, target_id, *, token=CLOUD):
    return client.post("/api/participant/actions", headers=headers(token), json={
        "action_id": action_id, "target_type": target_type,
        "target_id": target_id, "idempotency_key": action_id,
    })


def assessment_payload(service):
    event = service.run.cloud.audit[-1]
    return {
        "principal_id": "svc-cloud-backup", "confirmed_count": 5,
        "conclusion": "mock_access_only", "evidence_ids": [event["event_id"]],
    }


def test_read_only_cloud_api_requires_participant_auth_and_hides_branch_controls(portal):
    client, _service = portal
    assert client.get("/api/participant/cloud").status_code == 401
    assert client.get("/api/participant/cloud", headers=headers(STAFF)).status_code == 403
    stage(client)
    response = client.get("/api/participant/cloud", headers=headers(SOC))
    assert response.status_code == 200
    assert response.json()["state"]["exposure"][BUCKET]["confirmed_count"] == 5
    assert response.json()["mock"] is True
    for forbidden in ("dp3_preview", "checkpoint_results", "accepted_classifications", "STEPS"):
        assert forbidden not in response.text
    assert client.post("/api/participant/cloud", headers=headers(CLOUD), json={}).status_code == 405


def test_participant_can_contain_and_submit_without_receiving_answer_checks(portal):
    client, service = portal
    stage(client)
    payload = assessment_payload(service)
    assert action(client, "cloud.evidence.preserve", "cloud_bucket", BUCKET).status_code == 200
    assert action(client, "cloud.key.revoke", "cloud_key", KEY).status_code == 200
    assert action(client, "cloud.policy.restore", "cloud_bucket", BUCKET).status_code == 200
    response = client.post(
        "/api/participant/cloud/assessment", headers=headers(CLOUD), json=payload,
    )
    assert response.status_code == 200
    assert set(response.json()) == {"submission_id", "status", "run_id"}
    assert response.json()["status"] == "submitted"
    record = service.store.submissions(service.run.run_id)[0]
    assert record["actor_id"] == "cloud-responder"
    assert record["submission_type"] == "DP3"
    assert record["payload"] == payload
    client.post("/api/facilitator/advance", headers=headers(STAFF), json={"elapsed_seconds": 5700})
    resolved = client.post("/api/facilitator/checkpoints/dp3", headers=headers(STAFF))
    assert resolved.status_code == 200
    assert resolved.json()["evaluation"]["passed"] is True
    assert service.run.cloud.state.exposure[BUCKET]["confirmed_count"] == 5


@pytest.mark.parametrize("token", [SOC, ENDPOINT])
def test_role_forgery_cannot_grant_cloud_write_access(portal, token):
    client, service = portal
    stage(client)
    response = action(client, "cloud.key.revoke", "cloud_key", KEY, token=token)
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "role_denied"
    assert service.run.cloud.state.keys[KEY]["active"] is True
    forged = client.post("/api/participant/actions", headers=headers(token), json={
        "action_id": "cloud.key.revoke", "target_type": "cloud_key", "target_id": KEY,
        "idempotency_key": "forge", "actor": {"role": "cloud_responder"},
    })
    assert forged.status_code == 422


@pytest.mark.parametrize("token", [CLOUD, SOC, ENDPOINT])
def test_cloud_participants_cannot_resolve_or_export_staff_evidence(portal, token):
    client, _service = portal
    assert client.post("/api/facilitator/checkpoints/dp3", headers=headers(token)).status_code == 403
    assert client.get("/api/facilitator/exports/events.jsonl", headers=headers(token)).status_code == 403


@pytest.mark.parametrize("overrides", [
    {"confirmed_count": -1}, {"confirmed_count": 26}, {"confirmed_count": True},
    {"confirmed_count": "5"}, {"evidence_ids": []}, {"principal_id": ""},
    {"conclusion": "made_up"}, {"actor_id": "other-learner"},
    {"evidence_ids": ["x" * 129]},
])
def test_assessment_contract_rejects_invalid_fields(portal, overrides):
    client, service = portal
    stage(client)
    payload = assessment_payload(service)
    payload.update(overrides)
    response = client.post(
        "/api/participant/cloud/assessment", headers=headers(CLOUD), json=payload,
    )
    assert response.status_code == 422
    assert service.store.submissions(service.run.run_id) == []


def test_current_run_evidence_and_due_checkpoint_are_required(portal):
    client, service = portal
    stage(client)
    early = client.post("/api/facilitator/checkpoints/dp3", headers=headers(STAFF))
    assert early.status_code == 409
    payload = assessment_payload(service)
    payload["evidence_ids"] = ["fabricated-or-prior-run"]
    bad = client.post("/api/participant/cloud/assessment", headers=headers(CLOUD), json=payload)
    assert bad.status_code == 409
    assert service.run.cloud.assessment is None


def test_reset_archives_events_but_cleans_cloud_controls_audit_and_assessment(portal):
    client, service = portal
    stage(client)
    old = assessment_payload(service)
    assert client.post("/api/participant/cloud/assessment", headers=headers(CLOUD), json=old).status_code == 200
    action(client, "cloud.evidence.preserve", "cloud_bucket", BUCKET)
    action(client, "cloud.key.revoke", "cloud_key", KEY)
    client.post("/api/facilitator/stop", headers=headers(STAFF), json={"reason": "reset test"})
    result = client.post(
        "/api/facilitator/reset", headers=headers(STAFF), json={"new_run_id": "api-cloud-reset"},
    )
    assert result.status_code == 200
    assert result.json()["reset"]["cloud_baseline_verified"] is True
    assert service.run.cloud.audit == []
    assert service.run.cloud.assessment is None
    assert service.store.submissions("api-cloud-test")  # original evidence retained
    assert service.store.events(service.run.definition.exercise_id, "api-cloud-test")
    stage(client)
    stale = client.post("/api/participant/cloud/assessment", headers=headers(CLOUD), json=old)
    assert stale.status_code == 409


def test_missing_source_blocks_grading_and_duplicate_resolution_is_rejected(portal):
    client, service = portal
    stage(client)
    client.post("/api/facilitator/advance", headers=headers(STAFF), json={"elapsed_seconds": 5700})
    first = client.post("/api/facilitator/checkpoints/dp3", headers=headers(STAFF))
    assert first.status_code == 200
    second = client.post("/api/facilitator/checkpoints/dp3", headers=headers(STAFF))
    assert second.status_code == 409
    assert service.run.cloud.state.exposure[BUCKET]["confirmed_count"] == 25


def test_browser_cloud_controls_have_no_prepopulated_answers_or_external_assets(portal):
    client, _service = portal
    page = client.get("/participant")
    script = client.get("/static/participant.js")
    assert "Mock-cloud investigation" in page.text
    assert "svc-cloud-backup" not in page.text
    assert "simcorp-customer-exports" not in page.text
    assert "https://" not in page.text
    assert "https://" not in script.text
    assert "textContent" in script.text
    assert client.get("/facilitator").status_code == 200
