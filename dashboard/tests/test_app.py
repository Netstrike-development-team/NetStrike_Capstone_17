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
SERVICE_TOKEN = "identity-service-token-at-least-24-characters"


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
            SERVICE_TOKEN: PortalPrincipal(
                "simcorp-sso", "identity_capture_service"
            ),
        }
    )
    with TestClient(
        create_app(
            service,
            authenticator,
            sso_allowed_origins={"http://testserver"},
        )
    ) as client:
        yield client, service
    store.close()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _sso_headers(origin="http://testserver"):
    return {"Origin": origin}


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


def test_sso_browser_surface_is_offline_accessible_and_vendor_neutral(portal) -> None:
    client, _service = portal

    page = client.get("/sso")
    script = client.get("/static/sso.js")
    stylesheet = client.get("/static/sso.css")

    assert page.status_code == 200
    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert "SimCorp Access" in page.text
    assert 'aria-live="polite"' in page.text
    assert 'for="username"' in page.text
    assert "okta" not in page.text.casefold()
    assert "https://" not in page.text
    assert "https://" not in script.text
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_sso_rejects_unapproved_origins_and_external_accounts(portal) -> None:
    client, service = portal
    external_account = "real-person@external.example"
    raw_value = "-".join(("never", "persist", "this"))

    assert client.get(
        "/api/sso/state", headers=_sso_headers("https://outside.example")
    ).status_code == 403
    assert client.get(
        "/sso", headers={"Host": "outside.example"}
    ).status_code == 403
    response = client.post(
        "/api/sso/sign-in",
        headers=_sso_headers(),
        json={"username": external_account, "credential": raw_value},
    )

    assert response.status_code == 403
    serialized = str(
        service.store.events(service.run.definition.exercise_id, service.run.run_id)
    )
    assert external_account not in serialized
    assert raw_value not in serialized
    assert "identity.sign_in.rejected" in serialized


def test_sso_flow_emits_correlated_evidence_and_shows_suspicious_session(
    portal,
) -> None:
    client, service = portal
    raw_value = "-".join(("exercise", "access", "phrase"))
    sign_in = {
        "username": "sarah@simcorp.test",
        "credential": raw_value,
    }

    failed = client.post(
        "/api/sso/sign-in", headers=_sso_headers(), json=sign_in
    )
    challenge = client.post(
        "/api/sso/sign-in", headers=_sso_headers(), json=sign_in
    )

    assert failed.status_code == 200
    assert failed.json()["view"] == "failure"
    assert challenge.status_code == 200
    assert challenge.json()["view"] == "mfa"
    approved = client.post(
        "/api/sso/mfa",
        headers=_sso_headers(),
        json={
            "challenge_id": challenge.json()["challenge"]["id"],
            "decision": "approve",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["view"] == "success"
    assert approved.json()["has_suspicious_sessions"] is True

    sessions = client.post(
        "/api/sso/review-sessions", headers=_sso_headers(), json={}
    )
    assert sessions.status_code == 200
    assert sessions.json()["view"] == "suspicious_session"
    assert sessions.json()["sessions"][0]["id"] == "sess-red-01"

    timeline = service.identity_timeline()
    assert {item["run_id"] for item in timeline} == {"run-portal-test"}
    assert [item["action"] for item in timeline] == [
        "identity.sign_in.attempt",
        "identity.sign_in.attempt",
        "identity.mfa.challenge.delivered",
        "identity.mfa.challenge.approve",
        "identity.session.created",
        "identity.session.reviewed",
    ]
    assert raw_value not in str(timeline)
    assert raw_value not in str(
        service.store.events(service.run.definition.exercise_id, service.run.run_id)
    )


def test_sso_disabled_identity_shows_lockout_and_reset_restores_baseline(portal) -> None:
    client, service = portal
    service.run.identity_state.identities["sarah"]["enabled"] = False
    response = client.post(
        "/api/sso/sign-in",
        headers=_sso_headers(),
        json={
            "username": "sarah@simcorp.test",
            "credential": "exercise-only-value",
        },
    )

    assert response.status_code == 200
    assert response.json()["view"] == "locked"
    client.post("/api/facilitator/start", headers=_headers(FACILITATOR_TOKEN))
    client.post(
        "/api/facilitator/stop",
        headers=_headers(FACILITATOR_TOKEN),
        json={"reason": "SSO reset test"},
    )
    reset = client.post(
        "/api/facilitator/reset",
        headers=_headers(FACILITATOR_TOKEN),
        json={"new_run_id": "run-sso-reset"},
    )

    assert reset.status_code == 200
    assert reset.json()["reset"]["sso_baseline_verified"] is True
    assert service.sso_state()["view"] == "sign_in"
    assert service.run.identity_state.readiness_mismatches() == ()


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


def test_allowlisted_service_captures_safe_identity_evidence(portal) -> None:
    client, service = portal
    raw_value = "synthetic-only-password-value"
    payload = {
        "phase": "identity",
        "synthetic_identity": "sarah",
        "occurred_at": "2026-09-30T19:30:00Z",
        "action": "identity.sign_in.attempt",
        "result": "failure",
        "source_event_id": "sso-attempt-001",
        "credential_kind": "password",
        "synthetic_credential": raw_value,
    }

    denied = client.post(
        "/api/services/identity/interactions",
        headers=_headers(IDENTITY_TOKEN),
        json=payload,
    )
    captured = client.post(
        "/api/services/identity/interactions",
        headers=_headers(SERVICE_TOKEN),
        json=payload,
    )

    assert denied.status_code == 403
    assert captured.status_code == 200
    assert raw_value not in captured.text
    assert captured.json()["submission_reference"].startswith("hmac-sha256:")
    timeline = service.identity_timeline()
    assert timeline[0]["synthetic_identity"] == "sarah"
    assert timeline[0]["provenance"]["source_event_id"] == "sso-attempt-001"
    assert client.get(
        "/api/facilitator/identity-audit",
        headers=_headers(IDENTITY_TOKEN),
    ).status_code == 403
    timeline_response = client.get(
        "/api/facilitator/identity-audit",
        headers=_headers(FACILITATOR_TOKEN),
    )
    assert timeline_response.status_code == 200
    assert timeline_response.json()[0]["source_service"] == "simcorp-sso"
    stored = str(
        service.store.events(service.run.definition.exercise_id, service.run.run_id)
    )
    assert "identity.interaction.recorded" in stored
    assert raw_value not in stored
    export = client.get(
        "/api/facilitator/exports/events.jsonl",
        headers=_headers(FACILITATOR_TOKEN),
    )
    assert "identity.interaction.recorded" in export.text
    assert raw_value not in export.text


def test_identity_capture_rejects_unknown_secret_field_without_echoing_it(
    portal,
) -> None:
    client, service = portal
    raw_value = "must-never-appear-in-an-error"
    response = client.post(
        "/api/services/identity/interactions",
        headers=_headers(SERVICE_TOKEN),
        json={
            "phase": "identity",
            "synthetic_identity": "sarah",
            "action": "identity.sign_in.attempt",
            "result": "failure",
            "source_event_id": "sso-invalid-001",
            "password": raw_value,
        },
    )

    assert response.status_code == 409
    assert raw_value not in response.text
    assert service.identity_timeline() == []


def test_reset_removes_transient_identity_audit_and_verifies_baseline(portal) -> None:
    client, service = portal
    client.post(
        "/api/services/identity/interactions",
        headers=_headers(SERVICE_TOKEN),
        json={
            "phase": "identity",
            "synthetic_identity": "sarah",
            "action": "identity.sign_in.attempt",
            "result": "success",
            "source_event_id": "sso-reset-001",
        },
    )
    client.post("/api/facilitator/start", headers=_headers(FACILITATOR_TOKEN))
    client.post(
        "/api/facilitator/stop",
        headers=_headers(FACILITATOR_TOKEN),
        json={"reason": "reset audit test"},
    )

    response = client.post(
        "/api/facilitator/reset",
        headers=_headers(FACILITATOR_TOKEN),
        json={"new_run_id": "run-after-audit-reset"},
    )

    assert response.status_code == 200
    archive_identifier = response.json()["reset"]["review_archive_id"]
    assert service.review_archive(archive_identifier)["metadata"]["run_id"] == "run-portal-test"
    assert response.json()["reset"] == {
        "prior_run_id": "run-portal-test",
        "review_archive_id": archive_identifier,
        "identity_audit_records_deleted": 1,
        "identity_audit_baseline_verified": True,
        "sso_baseline_verified": True,
        "scheduled_mfa_baseline_verified": True,
        "profile_baseline_verified": True,
    }
    assert service.store.identity_audit(
        "operation-silent-spider", "run-portal-test"
    ) == []
