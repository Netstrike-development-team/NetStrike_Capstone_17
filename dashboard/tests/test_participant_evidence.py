"""Current-run evidence projection and authenticated local-viewer boundaries."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.evidence import project_signal
from dashboard.service import PortalService
from dashboard.store import PortalStore
from shared.events import EventBuilder, EventContext, entity

TOKENS = {role: f"evidence-test-{role}-token-at-least-24-characters"
          for role in ("soc_analyst", "identity_responder", "facilitator", "simulated_user")}


def headers(role="soc_analyst"):
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id="evidence-run")
    auth = TokenAuthenticator({token: PortalPrincipal(role, role)
                               for role, token in TOKENS.items()})
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


def start(client):
    assert client.post("/api/facilitator/prepare", headers=headers("facilitator")).status_code == 200
    assert client.post("/api/facilitator/start", headers=headers("facilitator")).status_code == 200


def test_evidence_page_is_public_shell_not_embedded_answers(portal):
    client, _ = portal
    page = client.get("/evidence")
    assert page.status_code == 200
    assert "not Splunk" in page.text
    assert "sess-red-01" not in page.text
    assert "factor-red-01" not in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "/evidence" in client.get("/participant").text


@pytest.mark.parametrize("role,status", [(None, 401), ("facilitator", 403),
                                         ("simulated_user", 403), ("soc_analyst", 200)])
def test_evidence_authentication_and_roles(portal, role, status):
    client, _ = portal
    assert client.get("/api/participant/evidence", headers=headers(role) if role else {}).status_code == status


def test_replay_signals_are_visible_without_changing_injects(portal):
    client, _ = portal
    start(client)
    client.post("/api/facilitator/advance", headers=headers("facilitator"),
                json={"elapsed_seconds": 600})
    signals = client.get("/api/participant/evidence", headers=headers()).json()
    types = [signal["event_type"] for signal in signals["signals"]]
    assert "identity.authentication.succeeded" in types
    assert "endpoint.remote_access.succeeded" in types
    assert len(client.get("/api/participant/state", headers=headers()).json()["injects"]) == 2
    assert "checkpoint_results" not in str(signals)
    assert "objective_ids" not in str(signals)
    assert "callback_verified" in str(signals)  # observable ticket fact, not rubric
    assert signals["environment"] == "local_synthetic_evidence_not_splunk"
    assert signals["ordering"] == "ingestion_sequence_not_occurrence_time"
    assert [s["sequence"] for s in signals["signals"]] == sorted(s["sequence"] for s in signals["signals"])


def test_own_response_receipt_only_not_other_actor_or_staff_actions(portal):
    client, service = portal
    start(client)
    response = client.post("/api/participant/actions", headers=headers("identity_responder"), json={
        "action_id": "identity.session.revoke", "target_type": "session",
        "target_id": "sess-red-01", "idempotency_key": "evidence-revoke",
    })
    assert response.status_code == 200
    own = client.get("/api/participant/evidence", headers=headers("identity_responder")).json()
    other = client.get("/api/participant/evidence", headers=headers()).json()
    receipts = [s for s in own["signals"] if s["category"] == "response"]
    assert len(receipts) == 1
    assert receipts[0]["actor_id"] == "identity_responder"
    assert receipts[0]["facts"]["status"] == "executed"
    assert not [s for s in other["signals"] if s["category"] == "response"]
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is False
    assert "effects" not in str(receipts)


@pytest.mark.parametrize("query", ["after_sequence=-1", "limit=0", "limit=101",
                                   "after_sequence=abc", "limit=1.5"])
def test_invalid_page_boundaries(portal, query):
    client, _ = portal
    assert client.get("/api/participant/evidence?" + query, headers=headers()).status_code == 422


def test_pages_are_unique_and_current_run_reset_does_not_leak_old_events(portal):
    client, _ = portal
    start(client)
    first = client.get("/api/participant/evidence?limit=2", headers=headers()).json()
    assert first["has_more"]
    second = client.get(f"/api/participant/evidence?after_sequence={first['next_sequence']}&limit=2",
                        headers=headers()).json()
    assert not {s["event_id"] for s in first["signals"]} & {s["event_id"] for s in second["signals"]}
    client.post("/api/facilitator/stop", headers=headers("facilitator"), json={"reason": "test"})
    client.post("/api/facilitator/reset", headers=headers("facilitator"), json={"new_run_id": "evidence-new-run"})
    reset = client.get("/api/participant/evidence", headers=headers()).json()
    assert reset["run_id"] == "evidence-new-run"
    assert reset["signals"] == []


def test_projection_omits_unreviewed_nested_data_paths_and_evaluator_checks():
    event = EventBuilder(EventContext(
        exercise_id="operation-silent-spider", run_id="projection-run", source_kind="module",
        source_component="test-source", producer_version="1.0.0",
    )).build(
        event_type="identity.authentication.succeeded", phase="identity",
        actor=entity("identity", "synthetic-user"), action="identity.authenticate",
        target=entity("service", "IDP01"), outcome_status="success", message="Observed fact",
        visibility="participant", data={"host": "FIN-WS01", "server_path": "/private/secret",
                                        "checks": {"rubric": True}, "source_ip": ["unreviewed"],
                                        "key_id": "x" * 513},
    )
    original = deepcopy(event)
    signal = project_signal(event, "learner")
    assert signal["facts"] == {"host": "FIN-WS01"}
    assert event == original
    for visibility in ("facilitator", "evaluator"):
        event["visibility"] = visibility
        assert project_signal(event, "learner") is None


def test_repeated_reads_are_read_only(portal):
    client, service = portal
    start(client)
    before = service.store.events(service.run.definition.exercise_id, service.run.run_id)
    for _ in range(3):
        assert client.get("/api/participant/evidence", headers=headers()).status_code == 200
    assert service.store.events(service.run.definition.exercise_id, service.run.run_id) == before
