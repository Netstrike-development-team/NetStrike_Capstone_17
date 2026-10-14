"""Participant-safe directory and facilitator profile readiness boundaries."""

from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore

TOKEN = "profile-soc-user-at-least-24-characters"
STAFF_TOKEN = "profile-facilitator-at-least-24-characters"


def test_directory_is_authenticated_read_only_and_not_an_answer_surface():
    store = PortalStore()
    service = PortalService(store, run_id="directory-run")
    authentication = TokenAuthenticator({TOKEN: PortalPrincipal("soc-01", "soc_analyst"),
                                         STAFF_TOKEN: PortalPrincipal("staff", "facilitator")})
    with TestClient(create_app(service, authentication, sso_allowed_origins={"http://testserver"})) as client:
        assert client.get("/api/participant/directory").status_code == 401
        assert client.get("/api/participant/directory", headers={"Authorization": f"Bearer {STAFF_TOKEN}"}).status_code == 403
        response = client.get("/api/participant/directory", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        profiles = response.json()
        assert len(profiles) == 20
        assert all(profile["username"].endswith("@simcorp.test") for profile in profiles)
        assert all(candidate["confidence"] == "inferred" for profile in profiles for candidate in profile["email_candidates"])
        assert all(key not in response.text for key in ("attack_value", "bindings", "callback_verified", "checkpoint_results", "seed"))
        assert client.post("/api/participant/directory", headers={"Authorization": f"Bearer {TOKEN}"}, json={"username": "forged"}).status_code == 405
        assert service.identity_timeline() == []
        assert service.run.identity_state.readiness_mismatches() == ()
        state = client.get("/api/facilitator/state", headers={"Authorization": f"Bearer {STAFF_TOKEN}"}).json()
        assert state["profile_initialization"]["profile_count"] == 20
        assert state["profile_initialization"]["catalog_sha256"] == service.run.profiles.fingerprint
        assert 'id="load-directory"' in client.get("/participant").text
        assert 'id="profile-summary"' in client.get("/facilitator").text
    store.close()
