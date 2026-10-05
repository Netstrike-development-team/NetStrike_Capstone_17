"""Current staff review exports pin a coherent run/snapshot without effects."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from dashboard.tests.test_aar_api import TOKENS, headers, judgment, post, stop
from orchestrator.aar import build_report, render_markdown, validate_bundle

RUN = "aar-api-run"
READS = ("report", "exports/bundle.json", "exports/aar.md")
EXPORTS = READS[1:]


@pytest.fixture
def portal(tmp_path):
    store = PortalStore(tmp_path / "review.sqlite3")
    service = PortalService(store, run_id=RUN, monotonic=lambda: 100.0)
    auth = TokenAuthenticator({value: PortalPrincipal(f"actor-{role}", role)
                               for role, value in TOKENS.items()})
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, service
    store.close()


def scoped(service, role="evaluator", **overrides):
    return {**headers(role), "X-Exercise-Run-ID": RUN,
            "X-Review-Bundle-SHA256": service.aar_bundle()["content_sha256"], **overrides}


@pytest.mark.parametrize("path", READS)
def test_stale_run_reads_are_rejected_without_effects(portal, path):
    client, service = portal
    before = service.aar_bundle()
    response = client.get(f"/api/evaluator/{path}", headers={**headers("evaluator"),
                          "X-Exercise-Run-ID": "old-private-run"})
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "old-private-run" not in response.text
    assert service.aar_bundle() == before


@pytest.mark.parametrize("path", READS)
def test_invalid_and_duplicate_run_header_block_reads(portal, path):
    client, service = portal
    before = service.aar_bundle()
    endpoint = f"/api/evaluator/{path}"
    assert client.get(endpoint, headers={**headers("evaluator"), "X-Exercise-Run-ID": " bad "}).status_code == 422
    assert client.get(endpoint, headers=list(headers("evaluator").items()) + [
        ("X-Exercise-Run-ID", RUN), ("X-Exercise-Run-ID", RUN),
    ]).status_code == 422
    assert service.aar_bundle() == before


@pytest.mark.parametrize("path", EXPORTS)
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "a" * 65, "private-value"])
def test_invalid_snapshot_header_is_generic_and_does_not_build_bundle(portal, monkeypatch, path, value):
    client, service = portal

    def forbidden():
        raise AssertionError("invalid header reached snapshot construction")

    monkeypatch.setattr(service, "aar_bundle", forbidden)
    response = client.get(f"/api/evaluator/{path}", headers={**headers("evaluator"),
                          "X-Review-Bundle-SHA256": value})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid review snapshot header"
    assert "private-value" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", EXPORTS)
def test_duplicate_snapshot_header_is_rejected(portal, path):
    client, service = portal
    before = service.aar_bundle()
    digest = before["content_sha256"]
    response = client.get(f"/api/evaluator/{path}", headers=list(headers("evaluator").items()) + [
        ("X-Review-Bundle-SHA256", digest), ("X-Review-Bundle-SHA256", digest),
    ])
    assert response.status_code == 422
    assert response.json()["detail"] == "ambiguous review snapshot header"
    assert service.aar_bundle() == before


@pytest.mark.parametrize("path", READS)
def test_snapshot_headers_do_not_grant_staff_authority_and_responses_are_not_cached(portal, path):
    client, service = portal
    endpoint = f"/api/evaluator/{path}"
    assert client.get(endpoint).status_code == 401
    for role in ("soc_analyst", "technical_operator", "identity_capture_service"):
        denied = client.get(endpoint, headers=scoped(service, role))
        assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
    for role in ("evaluator", "facilitator"):
        allowed = client.get(endpoint, headers=scoped(service, role))
        assert allowed.status_code == 200 and allowed.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", EXPORTS)
def test_changed_same_run_snapshot_rejects_old_download_and_new_snapshot_reproduces_report(portal, path):
    client, service = portal
    stop(client)
    old = scoped(service)
    assert post(client, judgment()).status_code == 200
    before = service.aar_bundle()
    stale = client.get(f"/api/evaluator/{path}", headers=old)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "review changed; refresh before exporting"
    assert service.aar_bundle() == before
    current = client.get(f"/api/evaluator/{path}", headers=scoped(service))
    assert current.status_code == 200
    if path.endswith(".json"):
        assert current.json() == before
        validate_bundle(json.loads(current.text))
    else:
        assert current.text == render_markdown(build_report(before))
    assert service.aar_bundle() == before


def test_legacy_unscoped_export_still_reads_latest_snapshot(portal):
    client, service = portal
    stop(client)
    assert post(client, judgment()).status_code == 200
    for path in READS:
        response = client.get(f"/api/evaluator/{path}", headers=headers("evaluator"))
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert client.get("/api/evaluator/exports/bundle.json", headers=headers("evaluator")).json() == service.aar_bundle()


@pytest.mark.parametrize("path", EXPORTS)
def test_snapshot_build_and_serialization_hold_scope_lock_against_reset(portal, monkeypatch, path):
    client, service = portal
    stop(client)
    expected = scoped(service)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    build = service.aar_bundle

    def held():
        bundle = build()
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
            assert service.run.run_id == RUN
        return bundle

    def reset():
        attempted.set()
        return client.post("/api/facilitator/reset", headers=headers("facilitator"),
                           json={"new_run_id": "review-next"})

    monkeypatch.setattr(service, "aar_bundle", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        downloading = pool.submit(client.get, f"/api/evaluator/{path}", headers=expected)
        try:
            assert entered.wait(5)
            resetting = pool.submit(reset)
            assert attempted.wait(5)
            assert not resetting.done()
        finally:
            release.set()
        response = downloading.result(timeout=5)
        assert response.status_code == 200
        # Reset can now build an archive using the same hook, after release.
        monkeypatch.setattr(service, "aar_bundle", build)
        assert resetting.result(timeout=5).status_code == 200
    assert RUN in response.text
    assert service.run.run_id == "review-next"
    assert client.get(f"/api/evaluator/{path}", headers=expected).status_code == 409
    assert post(client, judgment()).status_code == 409
