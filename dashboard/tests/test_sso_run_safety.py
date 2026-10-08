"""Contained SSO mutations share the existing optional current-run guard."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore

RUN = "sso-current-run"
USER = "sso-user-token-at-least-24-characters"
STAFF = "sso-staff-token-at-least-24-characters"
SIGN_IN = {"username": "sarah@simcorp.test", "credential": "synthetic-only-phrase"}
MUTATIONS = [
    ("sign-in", SIGN_IN),
    ("mfa", {"challenge_id": "old-challenge", "decision": "approve"}),
    ("scheduled-mfa", {"challenge_id": "old-challenge", "decision": "deny"}),
    ("review-sessions", {}),
]


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id=RUN, monotonic=lambda: 100.0)
    auth = TokenAuthenticator({USER: PortalPrincipal("synthetic-sarah", "simulated_user"),
                               STAFF: PortalPrincipal("staff", "facilitator")})
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


def headers(run=RUN, token=None):
    result = {"Origin": "http://testserver", "X-Exercise-Run-ID": run}
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def test_stale_sign_in_fails_before_audit_or_identity_change(portal):
    client, service = portal
    before = deepcopy(service.run.identity_state.__dict__)
    events = service.store.events(service.run.definition.exercise_id, RUN)
    response = client.post("/api/sso/sign-in", headers=headers("previous-run"), json=SIGN_IN)
    assert response.status_code == 409
    assert service.store.events(service.run.definition.exercise_id, RUN) == events
    assert service.run.identity_state.__dict__ == before


def snapshot(service):
    return deepcopy((service.run.identity_state.__dict__, service.sso_state(),
                     service.store.events(service.run.definition.exercise_id, service.run.run_id)))


@pytest.mark.parametrize("path,payload", MUTATIONS)
@pytest.mark.parametrize("run,expected", [("previous-run", 409), ("", 422),
                                         (" bad ", 422), ("x" * 129, 422), ("bad\tvalue", 422)])
def test_invalid_or_stale_scope_never_writes(portal, path, payload, run, expected):
    client, service = portal
    before = snapshot(service)
    response = client.post(f"/api/sso/{path}", headers=headers(run, USER), json=payload)
    assert response.status_code == expected
    assert snapshot(service) == before
    if run:
        assert run not in response.text


@pytest.mark.parametrize("path,payload", MUTATIONS)
def test_duplicate_run_header_is_rejected(portal, path, payload):
    client, service = portal
    before = snapshot(service)
    response = client.post(f"/api/sso/{path}", json=payload, headers=[
        ("Origin", "http://testserver"), ("Authorization", f"Bearer {USER}"),
        ("X-Exercise-Run-ID", RUN), ("X-Exercise-Run-ID", RUN),
    ])
    assert response.status_code == 422
    assert snapshot(service) == before


@pytest.mark.parametrize("scoped", [False, True])
def test_current_and_legacy_manual_flows_have_coherent_snapshots(portal, scoped):
    client, _service = portal
    hdr = headers() if scoped else {"Origin": "http://testserver"}
    initial = client.get("/api/sso/state", headers=hdr)
    assert initial.headers["cache-control"] == "no-store"
    assert initial.json()["run_id"] == RUN
    assert client.post("/api/sso/sign-in", headers=hdr, json=SIGN_IN).json()["view"] == "failure"
    challenge = client.post("/api/sso/sign-in", headers=hdr, json=SIGN_IN).json()["challenge"]["id"]
    approved = client.post("/api/sso/mfa", headers=hdr, json={"challenge_id": challenge, "decision": "approve"})
    assert approved.status_code == 200
    reviewed = client.post("/api/sso/review-sessions", headers=hdr, json={})
    assert reviewed.status_code == 200
    for response in (approved, reviewed):
        assert response.json()["run_id"] == RUN
        assert response.json()["exercise_state"] == "ready"
        assert response.json()["scheduled_result"] is None
    assert reviewed.json()["view"] == "suspicious_session"


@pytest.mark.parametrize("scoped", [False, True])
def test_current_and_legacy_scheduled_decisions(portal, scoped):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers(token=STAFF)).status_code == 200
    assert client.post("/api/facilitator/advance", headers=headers(token=STAFF), json={"elapsed_seconds": 30}).status_code == 200
    before = snapshot(service)
    challenge = service.sso_state()["challenge"]["id"]
    payload = {"challenge_id": challenge, "decision": "deny"}
    for token, expected in [(None, 401), (STAFF, 403)]:
        assert client.post("/api/sso/scheduled-mfa", headers=headers(token=token), json=payload).status_code == expected
        assert snapshot(service) == before
    hdr = headers(token=USER)
    if not scoped:
        del hdr["X-Exercise-Run-ID"]
    response = client.post("/api/sso/scheduled-mfa", headers=hdr, json=payload)
    assert response.status_code == 200
    assert response.json()["run_id"] == RUN
    assert response.json()["scheduled_result"]["outcome"] == "denied"


def test_current_header_keeps_origin_synthetic_and_body_boundaries(portal):
    client, service = portal
    for payload, hdr, expected in [
        (SIGN_IN, {**headers(), "Origin": "https://outside.invalid"}, 403),
        ({**SIGN_IN, "username": "real@example.com"}, headers(), 403),
        ({**SIGN_IN, "actor": "spoof"}, headers(), 422),
        ({**SIGN_IN, "credential": "x" * 5000}, headers(), 413),
    ]:
        before = snapshot(service)
        response = client.post("/api/sso/sign-in", headers=hdr, json=payload)
        assert response.status_code == expected
        # The pre-existing real-account rejection intentionally emits safe audit.
        if payload.get("username") != "real@example.com":
            assert snapshot(service) == before
    assert SIGN_IN["credential"] not in str(service.identity_timeline())


def test_old_tab_after_real_reset_cannot_add_sign_in_to_new_run(portal):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers(token=STAFF)).status_code == 200
    assert client.post("/api/facilitator/stop", headers=headers(token=STAFF), json={"reason": "Reset test"}).status_code == 200
    assert client.post("/api/facilitator/reset", headers=headers(token=STAFF), json={"new_run_id": "next-run"}).status_code == 200
    before = snapshot(service)
    assert client.post("/api/sso/sign-in", headers=headers(), json=SIGN_IN).status_code == 409
    assert snapshot(service) == before
    assert client.post("/api/sso/sign-in", headers=headers("next-run"), json=SIGN_IN).json()["run_id"] == "next-run"


def test_snapshot_holds_run_lock_across_manual_and_scheduled_state(portal, monkeypatch):
    _client, service = portal
    service.stop_run("Snapshot/reset test", PortalPrincipal("staff", "facilitator"))
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    original = service.sso.state

    def held():
        state = original()
        entered.set()
        assert release.wait(5)
        return state

    def competing_write():
        attempted.set()
        service.reset_run(new_run_id="competing-run")

    monkeypatch.setattr(service.sso, "state", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(service.sso_state)
        try:
            assert entered.wait(5)
            writing = pool.submit(competing_write)
            assert attempted.wait(5)
            assert not writing.done()
        finally:
            release.set()
        assert reading.result(timeout=5)["run_id"] == RUN
        writing.result(timeout=5)
