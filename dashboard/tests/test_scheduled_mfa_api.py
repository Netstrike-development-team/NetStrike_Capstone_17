"""Authenticated scheduled MFA decisions, exports, and SSO presentation."""

import json

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from shared.events import EventValidator

FAC_TOKEN = "mfa-facilitator-at-least-24-characters"
USER_TOKEN = "mfa-simulated-user-at-least-24-characters"
SOC_TOKEN = "mfa-soc-analyst-at-least-24-characters"
TECH_TOKEN = "mfa-technical-operator-at-least-24-characters"


def headers(token):
    return {"Authorization": f"Bearer {token}", "Origin": "http://testserver"}


@pytest.fixture
def system():
    store = PortalStore()
    service = PortalService(store, run_id="run-scheduled-mfa-api")
    authentication = TokenAuthenticator({
        FAC_TOKEN: PortalPrincipal("staff-alice", "facilitator"),
        USER_TOKEN: PortalPrincipal("synthetic-sarah", "simulated_user"),
        SOC_TOKEN: PortalPrincipal("soc-bob", "soc_analyst"),
        TECH_TOKEN: PortalPrincipal("operator", "technical_operator"),
    })
    with TestClient(create_app(service, authentication, sso_allowed_origins={"http://testserver"})) as client:
        assert client.post("/api/facilitator/start", headers=headers(FAC_TOKEN)).status_code == 200
        assert client.post("/api/facilitator/advance", headers=headers(FAC_TOKEN), json={"elapsed_seconds": 30}).status_code == 200
        yield client, service
    store.close()


@pytest.mark.parametrize("token,path", [
    (USER_TOKEN, "/api/sso/scheduled-mfa"),
    (FAC_TOKEN, "/api/facilitator/mfa/decision"),
])
def test_role_bound_human_decision_and_canonical_export(system, token, path):
    client, service = system
    visible = client.get("/api/sso/state").json()
    assert visible["view"] == "mfa"
    assert visible["challenge"]["kind"] == "scheduled"
    assert "seed" not in str(visible)
    challenge = visible["challenge"]["id"]
    response = client.post(path, headers=headers(token), json={"challenge_id": challenge, "decision": "approve"})
    assert response.status_code == 200
    assert response.json()["scheduled_result"]["outcome"] == "approved"
    assert response.json()["view"] == "sign_in"  # not a participant sign-in or real session
    assert "sess-sso-current" not in service.run.identity_state.sessions
    export = client.get("/api/facilitator/exports/events.jsonl", headers=headers(FAC_TOKEN))
    events = [json.loads(line) for line in export.text.splitlines()]
    delivered, approved = [event for event in events if event["source"]["component"] == "scheduled-mfa"]
    assert approved["actor"]["id"] == ("staff-alice" if token == FAC_TOKEN else "synthetic-sarah")
    assert delivered["correlation_ids"] == approved["correlation_ids"]
    for event in events:
        EventValidator().validate(event)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


@pytest.mark.parametrize("token,path,expected", [
    (None, "/api/sso/scheduled-mfa", 401),
    (SOC_TOKEN, "/api/sso/scheduled-mfa", 403),
    (FAC_TOKEN, "/api/sso/scheduled-mfa", 403),
    (USER_TOKEN, "/api/facilitator/mfa/decision", 403),
    (TECH_TOKEN, "/api/facilitator/mfa/decision", 403),
])
def test_other_roles_cannot_change_outcome(system, token, path, expected):
    client, service = system
    before = service.run.mfa.snapshot()
    response = client.post(path, headers=headers(token) if token else {}, json={"challenge_id": before["pending"]["id"], "decision": "approve"})
    assert response.status_code == expected
    assert service.run.mfa.snapshot() == before


def test_unicode_bearer_is_rejected_without_a_server_error(system):
    client, service = system
    before = service.run.mfa.snapshot()
    response = client.post("/api/sso/scheduled-mfa", headers={"Authorization": b"Bearer \xc3\xa9-not-a-token"},
                           json={"challenge_id": before["pending"]["id"], "decision": "approve"})
    assert response.status_code == 401
    assert service.run.mfa.snapshot() == before


def test_scheduled_decision_origin_fields_and_size_boundaries(system):
    client, service = system
    before = service.run.mfa.snapshot()
    payload = {"challenge_id": before["pending"]["id"], "decision": "approve"}
    assert client.post("/api/sso/scheduled-mfa", headers={**headers(USER_TOKEN), "Origin": "https://public.invalid"}, json=payload).status_code == 403
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json={**payload, "actor": "staff-alice"}).status_code == 422
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json={**payload, "decision": []}).status_code == 409
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json={**payload, "challenge_id": "x" * 5000}).status_code == 413
    assert service.run.mfa.snapshot() == before


def test_pause_stop_and_reset_invalidate_old_decisions(system):
    client, service = system
    old_id = service.run.mfa.snapshot()["pending"]["id"]
    payload = {"challenge_id": old_id, "decision": "approve"}
    assert client.post("/api/facilitator/pause", headers=headers(FAC_TOKEN)).status_code == 200
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json=payload).status_code == 409
    assert client.get("/api/sso/state").json()["challenge"]["expires_in_seconds"] == 30
    assert client.post("/api/facilitator/stop", headers=headers(FAC_TOKEN), json={"reason": "test"}).status_code == 200
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json=payload).status_code == 409
    assert client.post("/api/facilitator/reset", headers=headers(FAC_TOKEN), json={"new_run_id": "run-scheduled-mfa-api"}).status_code == 409
    assert client.post("/api/facilitator/reset", headers=headers(FAC_TOKEN), json={"new_run_id": "run-mfa-api-next"}).status_code == 200
    assert service.run.mfa.snapshot()["history"] == []
    assert client.post("/api/facilitator/start", headers=headers(FAC_TOKEN)).status_code == 200
    assert client.post("/api/facilitator/advance", headers=headers(FAC_TOKEN), json={"elapsed_seconds": 30}).status_code == 200
    assert client.post("/api/sso/scheduled-mfa", headers=headers(USER_TOKEN), json=payload).status_code == 409


def test_existing_local_endpoint_cannot_approve_scheduled_id(system):
    client, service = system
    before = service.run.mfa.snapshot()
    response = client.post("/api/sso/mfa", headers={"Origin": "http://testserver"}, json={"challenge_id": before["pending"]["id"], "decision": "approve"})
    assert response.status_code == 409
    assert service.run.mfa.snapshot() == before


def test_assets_offer_both_control_surfaces(system):
    client, _service = system
    assert 'id="mfa-access-token"' in client.get("/sso").text
    assert 'id="scheduled-result"' in client.get("/sso").text
    assert 'id="mfa-deny"' in client.get("/facilitator").text
    assert "/api/sso/scheduled-mfa" in client.get("/static/sso.js").text
