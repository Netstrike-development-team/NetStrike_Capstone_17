"""Role separation and identity-slice portal workflow tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore


FACILITATOR_TOKEN = "facilitator-token-at-least-24-characters"
IDENTITY_TOKEN = "identity-user-token-at-least-24-characters"
ENDPOINT_TOKEN = "endpoint-user-token-at-least-24-characters"
LEAD_TOKEN = "incident-lead-token-at-least-24-characters"


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id="run-portal-test")
    authenticator = TokenAuthenticator(
        {
            FACILITATOR_TOKEN: PortalPrincipal("fac-01", "facilitator"),
            IDENTITY_TOKEN: PortalPrincipal("learner-id", "identity_responder"),
            ENDPOINT_TOKEN: PortalPrincipal("learner-endpoint", "endpoint_responder"),
            LEAD_TOKEN: PortalPrincipal("learner-lead", "incident_lead"),
        }
    )
    with TestClient(create_app(service, authenticator)) as client:
        yield client, service
    store.close()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public_but_portal_state_requires_authentication(portal) -> None:
    client, _service = portal

    assert client.get("/health").status_code == 200
    assert client.get("/api/participant/state").status_code == 401
    assert client.get(
        "/api/facilitator/state", headers=_headers(IDENTITY_TOKEN)
    ).status_code == 403


def test_facilitator_controls_expose_only_injects_to_participant(portal) -> None:
    client, _service = portal
    facilitator_headers = _headers(FACILITATOR_TOKEN)

    assert client.post(
        "/api/facilitator/prepare", headers=facilitator_headers
    ).status_code == 200
    assert client.post(
        "/api/facilitator/start", headers=facilitator_headers
    ).status_code == 200
    assert client.post(
        "/api/facilitator/advance",
        headers=facilitator_headers,
        json={"elapsed_seconds": 300},
    ).status_code == 200

    response = client.get(
        "/api/participant/state", headers=_headers(IDENTITY_TOKEN)
    )
    assert response.status_code == 200
    state = response.json()
    assert [inject["msel_id"] for inject in state["injects"]] == [
        "MSEL-01",
        "MSEL-02",
    ]
    serialized = str(state)
    assert "callback_verified" not in serialized
    assert "checkpoint_results" not in serialized


def test_participant_identity_action_uses_token_role_and_rejects_forgery(portal) -> None:
    client, service = portal
    client.post("/api/facilitator/start", headers=_headers(FACILITATOR_TOKEN))
    payload = {
        "action_id": "identity.session.revoke",
        "target_type": "session",
        "target_id": "sess-red-01",
        "idempotency_key": "portal-revoke-session",
    }

    response = client.post(
        "/api/participant/actions", headers=_headers(IDENTITY_TOKEN), json=payload
    )
    assert response.status_code == 200
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is False

    forged = {**payload, "idempotency_key": "forged", "role": "facilitator"}
    response = client.post(
        "/api/participant/actions", headers=_headers(LEAD_TOKEN), json=forged
    )
    assert response.status_code == 422


def test_dp1_submission_is_scored_and_persisted(portal) -> None:
    client, service = portal
    headers = _headers(FACILITATOR_TOKEN)
    client.post("/api/facilitator/start", headers=headers)
    client.post(
        "/api/facilitator/advance",
        headers=headers,
        json={"elapsed_seconds": 2400},
    )

    response = client.post(
        "/api/participant/checkpoints/dp1",
        headers=_headers(LEAD_TOKEN),
        json={
            "affected_identity": "Sarah Mitchell (sarah)",
            "classification": "Likely account compromise",
            "evidence": [
                {"reference_id": "HD-1042", "source": "helpdesk"},
                {"reference_id": "factor-red-01", "source": "identity"},
                {"reference_id": "sess-red-01", "source": "identity"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["passed"] is True
    assert service.store.submissions("run-portal-test")[0]["submission_type"] == "DP1"


def test_emergency_stop_blocks_actions_and_reset_starts_clean_run(portal) -> None:
    client, service = portal
    headers = _headers(FACILITATOR_TOKEN)
    client.post("/api/facilitator/start", headers=headers)

    stopped = client.post(
        "/api/facilitator/stop",
        headers=headers,
        json={"reason": "automated safety test"},
    )
    assert stopped.status_code == 200

    action = client.post(
        "/api/participant/actions",
        headers=_headers(IDENTITY_TOKEN),
        json={
            "action_id": "identity.session.revoke",
            "target_type": "session",
            "target_id": "sess-red-01",
            "idempotency_key": "after-stop",
        },
    )
    assert action.status_code == 403

    reset = client.post(
        "/api/facilitator/reset",
        headers=headers,
        json={"new_run_id": "run-portal-reset"},
    )
    assert reset.status_code == 200
    assert service.run.run_id == "run-portal-reset"
    assert service.run.identity_state.readiness_mismatches() == ()


def test_interactive_api_docs_are_disabled(portal) -> None:
    client, _service = portal
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_offline_browser_surfaces_have_security_headers_and_no_answer_ids(
    portal,
) -> None:
    client, _service = portal

    participant = client.get("/participant")
    facilitator = client.get("/facilitator")
    stylesheet = client.get("/static/styles.css")

    assert participant.status_code == 200
    assert facilitator.status_code == 200
    assert stylesheet.status_code == 200
    assert "default-src 'self'" in participant.headers["content-security-policy"]
    assert participant.headers["x-frame-options"] == "DENY"
    assert "Participant response console" in participant.text
    assert "Facilitator control room" in facilitator.text
    for answer_id in ("sess-red-01", "factor-red-01", "svc-print-sync"):
        assert answer_id not in participant.text
    assert "https://" not in participant.text
    assert "https://" not in facilitator.text


def test_evidence_exports_are_facilitator_only_and_correlated(portal) -> None:
    client, _service = portal
    client.post("/api/facilitator/start", headers=_headers(FACILITATOR_TOKEN))

    assert client.get(
        "/api/facilitator/exports/events.jsonl",
        headers=_headers(IDENTITY_TOKEN),
    ).status_code == 403

    jsonl = client.get(
        "/api/facilitator/exports/events.jsonl",
        headers=_headers(FACILITATOR_TOKEN),
    )
    csv_response = client.get(
        "/api/facilitator/exports/events.csv",
        headers=_headers(FACILITATOR_TOKEN),
    )

    assert jsonl.status_code == 200
    assert "run-portal-test" in jsonl.text
    assert jsonl.headers["content-disposition"].endswith(
        '"run-portal-test-events.jsonl"'
    )
    assert csv_response.status_code == 200
    assert "exercise_id,run_id" in csv_response.text
