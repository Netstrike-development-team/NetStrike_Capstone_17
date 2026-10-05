"""Learner mutations cannot cross a concurrent staff reset with a run guard."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from dashboard.tests import test_recovery_api as recovery
from orchestrator.impact import FULL_SCENARIO_PATH

RUN = "learner-current"
ROLES = ("facilitator", "technical_operator", "evaluator", "identity_responder",
         "soc_analyst", "cloud_responder", "simulated_user")
TOKENS = {role: f"learner-safety-{role}-token-at-least-24-characters" for role in ROLES}


def headers(role="facilitator", run_id=RUN):
    return {"Authorization": f"Bearer {TOKENS[role]}", "X-Exercise-Run-ID": run_id}


@pytest.fixture
def portal(tmp_path):
    root = tmp_path / "disposable"
    root.mkdir()
    store = PortalStore(tmp_path / "portal.sqlite3")
    service = PortalService(store, run_id=RUN, scenario_path=FULL_SCENARIO_PATH,
                            impact_root=root, monotonic=lambda: 100.0)
    auth = TokenAuthenticator({token: PortalPrincipal(f"actor-{role}", role)
                               for role, token in TOKENS.items()})
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


ACTION = {"action_id": "identity.session.revoke", "target_type": "session",
          "target_id": "sess-red-01", "idempotency_key": "same-key-across-runs"}
DP1 = {"affected_identity": "sarah", "classification": "account compromise", "evidence": [
    {"reference_id": "HD-1042", "source": "helpdesk"},
    {"reference_id": "factor-red-01", "source": "identity"},
    {"reference_id": "sess-red-01", "source": "identity"},
]}
MUTATIONS = [
    ("actions", ACTION), ("checkpoints/dp1", DP1),
    ("cloud/assessment", {"principal_id": "svc-cloud-backup", "confirmed_count": 5,
                           "conclusion": "mock_access_only", "evidence_ids": ["cloud-event"]}),
    ("recovery/action", {"action_id": "recovery.fixture.restore", "fixture_id": recovery.FIXTURE,
                          "key": "restore-key", "dry_run": False}),
    ("recovery/brief", {"confirmed_scope": "Synthetic hosts", "confirmed_cloud_records": 5,
                        "business_impact": "Decoys unavailable", "actions_taken": "Restored fixture",
                        "remaining_risk": "External transfer unproven",
                        "recommendations": ["Review access", "Review helpdesk"], "evidence_ids": ["event"]}),
    ("timeline", {"run_id": RUN, "entries": [
        {"occurred_at": "2026-10-05T12:00:00Z", "statement_type": "fact",
         "event_id": f"event-{index}", "summary": "Observed synthetic event"} for index in range(6)
    ]}),
]


def snapshot(service):
    """Exclude clock diagnostics; compare actual state, evidence and fixture files."""
    state = service.facilitator_state()
    return deepcopy({key: state[key] for key in state if key not in {"clock", "readiness"}})


@pytest.mark.parametrize("path,payload", MUTATIONS)
def test_stale_learner_requests_fail_before_any_write(portal, path, payload):
    client, service = portal
    before = snapshot(service)
    fixture = service.run.impact.fixture.inspect()
    response = client.post(f"/api/participant/{path}", json=payload,
                           headers=headers("identity_responder", "previous-private-run"))
    assert response.status_code == 409
    assert response.json()["detail"] == "run changed; refresh before acting or exporting"
    assert "previous-private-run" not in response.text
    assert snapshot(service) == before
    assert service.run.impact.fixture.inspect() == fixture


@pytest.mark.parametrize("value", ["", " bad ", "x" * 129, "bad\tvalue"])
def test_invalid_header_fails_without_ledger_or_state_changes(portal, value):
    client, service = portal
    before = snapshot(service)
    response = client.post("/api/participant/actions", json=ACTION,
                           headers=headers("identity_responder", value))
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid exercise run header"
    assert snapshot(service) == before


def test_duplicate_header_fails_closed(portal):
    client, service = portal
    before = snapshot(service)
    response = client.post("/api/participant/actions", json=ACTION, headers=[
        ("Authorization", f"Bearer {TOKENS['identity_responder']}"),
        ("X-Exercise-Run-ID", RUN), ("X-Exercise-Run-ID", RUN),
    ])
    assert response.status_code == 422
    assert snapshot(service) == before


@pytest.mark.parametrize("role", ["facilitator", "evaluator", "simulated_user"])
def test_run_guard_does_not_grant_learner_authority(portal, role):
    client, service = portal
    before = snapshot(service)
    assert client.post("/api/participant/actions", json=ACTION, headers=headers(role)).status_code == 403
    assert snapshot(service) == before


def test_current_guard_keeps_role_target_lifecycle_and_idempotency_rules(portal):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    assert client.post("/api/participant/actions", json=ACTION, headers=headers("soc_analyst")).status_code == 403
    assert client.post("/api/participant/actions", json={**ACTION, "target_id": "not-allowlisted"},
                       headers=headers("identity_responder")).status_code == 403
    first = client.post("/api/participant/actions", json=ACTION, headers=headers("identity_responder"))
    assert first.status_code == 200
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is False
    replay = client.post("/api/participant/actions", json=ACTION,
                         headers=headers("identity_responder"))
    assert replay.status_code == 200 and replay.json()["cached"] is True
    assert {key: value for key, value in replay.json().items() if key != "cached"} == {
        key: value for key, value in first.json().items() if key != "cached"
    }
    assert client.post("/api/facilitator/stop", json={"reason": "Safety boundary"}, headers=headers()).status_code == 200
    assert client.post("/api/participant/actions", json={**ACTION, "idempotency_key": "after-stop"},
                       headers=headers("identity_responder")).status_code == 403


def test_legacy_header_omission_remains_supported(portal):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    legacy = {"Authorization": f"Bearer {TOKENS['identity_responder']}"}
    assert client.post("/api/participant/actions", json=ACTION, headers=legacy).status_code == 200
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is False


def test_action_scope_check_and_execution_hold_one_lock_against_reset(portal, monkeypatch):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    submit = service.submit_action

    def held(*args, **kwargs):
        result = submit(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        assert service.run.run_id == RUN
        return result

    def reset():
        attempted.set()
        assert client.post("/api/facilitator/stop", json={"reason": "Concurrent reset"},
                           headers=headers()).status_code == 200
        return client.post("/api/facilitator/reset", json={"new_run_id": "learner-next"}, headers=headers())

    monkeypatch.setattr(service, "submit_action", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        action = pool.submit(client.post, "/api/participant/actions", json=ACTION,
                             headers=headers("identity_responder"))
        try:
            assert entered.wait(5)
            resetting = pool.submit(reset)
            assert attempted.wait(5)
            assert not resetting.done()
        finally:
            release.set()
        assert action.result(timeout=5).status_code == 200
        assert resetting.result(timeout=5).status_code == 200
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is True
    assert client.post("/api/participant/actions", json=ACTION,
                       headers=headers("identity_responder")).status_code == 409


@pytest.mark.parametrize("terminal", ["stop", "complete"])
def test_full_play_recovery_archive_reset_and_new_learner_action(portal, terminal):
    """Compose real HTTP roles, all checkpoints and reset; not live range proof."""
    client, service = portal
    assert client.post("/api/facilitator/prepare", headers=headers()).status_code == 200
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    assert client.post("/api/participant/checkpoints/dp1", json=DP1, headers=headers("soc_analyst")).status_code == 200
    for seconds, checkpoint in ((3600, "dp2"), (5700, "dp3"), (6600, "dp4")):
        assert client.post("/api/facilitator/advance", json={"elapsed_seconds": seconds}, headers=headers()).status_code == 200
        result = client.post(f"/api/facilitator/checkpoints/{checkpoint}", headers=headers())
        assert result.status_code == 200 and result.json()["evaluation"]["passed"] is False
    for action_id in ("recovery.fixture.restore", "recovery.health.validate"):
        assert client.post("/api/participant/recovery/action", headers=headers("cloud_responder"), json={
            "action_id": action_id, "fixture_id": recovery.FIXTURE, "key": action_id, "dry_run": False,
        }).status_code == 200
    assert client.post("/api/participant/recovery/brief", json=recovery.payload(service),
                       headers=headers("soc_analyst")).status_code == 200
    if terminal == "stop":
        assert client.post("/api/facilitator/stop", json={"reason": "Preserve partial-play review"}, headers=headers()).status_code == 200
    else:
        assert client.post("/api/facilitator/advance", json={"elapsed_seconds": 7800}, headers=headers()).status_code == 200
        assert service.run.impact.final_review.passed
    assert service.run.impact.fixture.inspect()["originals_unchanged"]
    assert client.post("/api/participant/actions", json=ACTION,
                       headers=headers("identity_responder")).status_code == 403
    bundle = client.get("/api/evaluator/exports/bundle.json", headers=headers("evaluator")).json()
    assert bundle["checkpoint_ids"] == ["DP1", "DP2", "DP3", "DP4"]
    capture = client.post("/api/evaluator/archives", headers=headers("evaluator"), json={
        "run_id": RUN, "expected_bundle_sha256": bundle["content_sha256"],
    })
    assert capture.status_code == 200
    identifier = capture.json()["metadata"]["archive_id"]
    path = f"/api/evaluator/archives/{identifier}/bundle.json"
    assert client.get(path, headers=headers("soc_analyst")).status_code == 403
    raw = client.get("/api/facilitator/exports/events.jsonl", headers=headers())
    assert raw.status_code == 200
    assert all(json.loads(line)["run_id"] == RUN for line in raw.text.splitlines())
    reset = client.post("/api/facilitator/reset", headers=headers(), json={"new_run_id": "learner-next"})
    assert reset.status_code == 200
    assert client.get(path, headers=headers("evaluator", "learner-next")).json() == bundle
    assert service.store.submissions("learner-next") == []
    assert client.post("/api/facilitator/start", headers=headers(run_id="learner-next")).status_code == 200
    before = snapshot(service)
    assert client.post("/api/participant/actions", json=ACTION, headers=headers("identity_responder")).status_code == 409
    assert snapshot(service) == before
    assert client.post("/api/participant/actions", json=ACTION,
                       headers=headers("identity_responder", "learner-next")).status_code == 200
    assert service.run.identity_state.sessions["sess-red-01"]["active"] is False
