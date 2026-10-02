"""End-of-play objective review, independent role, audit and offline replay."""

import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.aar import build_report, participant_feedback, render_markdown

TOKENS = {
    role: f"aar-{role}-token-at-least-24-characters"
    for role in (
        "facilitator",
        "evaluator",
        "technical_operator",
        "soc_analyst",
        "identity_capture_service",
    )
}


def headers(role):
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@pytest.fixture
def portal():
    store = PortalStore()
    service = PortalService(store, run_id="aar-api-run")
    auth = TokenAuthenticator(
        {
            value: PortalPrincipal(f"actor-{role}", role)
            for role, value in TOKENS.items()
        }
    )
    with TestClient(
        create_app(service, auth, sso_allowed_origins={"http://testserver"})
    ) as client:
        yield client, service
    store.close()


def stop(client):
    client.post("/api/facilitator/start", headers=headers("facilitator"))
    response = client.post(
        "/api/facilitator/stop",
        headers=headers("facilitator"),
        json={"reason": "Platform outage before complete observation"},
    )
    assert response.status_code == 200


def judgment(objective="LO1", **overrides):
    return {
        "run_id": "aar-api-run",
        "objective_id": objective,
        "rating": "not_observed",
        "rationale": "Telemetry unavailable; no learner failure inferred.",
        "evidence_ids": [],
        "expected_revision": 0,
        "override_reason": "",
        "platform_reason": "Play stopped before this objective was observable.",
        "improvement_actions": [],
        **overrides,
    }


def post(client, payload, role="evaluator"):
    return client.post("/api/evaluator/judgments", headers=headers(role), json=payload)


@pytest.mark.parametrize("path", ["report", "exports/bundle.json", "exports/aar.md"])
def test_staff_reads_require_evaluator_or_facilitator(portal, path):
    client, _ = portal
    endpoint = f"/api/evaluator/{path}"
    assert client.get(endpoint).status_code == 401
    for role in ("soc_analyst", "technical_operator", "identity_capture_service"):
        assert client.get(endpoint, headers=headers(role)).status_code == 403
    for role in ("evaluator", "facilitator"):
        assert client.get(endpoint, headers=headers(role)).status_code == 200
    assert (
        client.get("/api/facilitator/state", headers=headers("evaluator")).status_code
        == 403
    )
    assert (
        client.post("/api/facilitator/start", headers=headers("evaluator")).status_code
        == 403
    )


def test_review_is_end_of_play_only_and_role_bounded(portal):
    client, _ = portal
    assert post(client, judgment()).status_code == 409
    stop(client)
    for role in ("soc_analyst", "technical_operator", "identity_capture_service"):
        assert post(client, judgment(), role).status_code == 403
    assert post(client, judgment()).status_code == 200


def test_append_only_revisions_and_unchanged_branches(portal):
    client, service = portal
    stop(client)
    before = dict(service.run.controller.checkpoint_results)
    first = post(client, judgment())
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert post(client, judgment()).status_code == 409
    assert post(client, judgment(expected_revision=1)).status_code == 409
    assert (
        post(
            client,
            judgment(
                expected_revision=1,
                override_reason="Second evaluator clarified platform scope.",
            ),
            "facilitator",
        ).status_code
        == 200
    )
    report = client.get("/api/evaluator/report", headers=headers("evaluator")).json()
    history = report["objectives"][0]["history"]
    assert len(history) == 2
    assert history[1]["supersedes_event_id"] == first.json()["event_id"]
    assert history[0]["evaluator_id"] == "actor-evaluator"
    assert history[1]["evaluator_id"] == "actor-facilitator"
    assert service.run.controller.checkpoint_results == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"actor_id": "someone-else"},
        {"expected_revision": True},
        {"rating": "pass"},
        {"rationale": " "},
        {"evidence_ids": ["foreign-run-event"]},
        {"platform_reason": ""},
        {"rating": "not_performed", "evidence_ids": []},
        {"run_id": "different-run"},
        {"improvement_actions": [{"description": "missing owner"}]},
    ],
)
def test_invalid_or_forged_review_is_rejected_without_writes(portal, overrides):
    client, service = portal
    stop(client)
    count = len(
        service.store.events(service.run.definition.exercise_id, service.run.run_id)
    )
    assert post(client, judgment(**overrides)).status_code in {409, 422}
    assert (
        len(
            service.store.events(service.run.definition.exercise_id, service.run.run_id)
        )
        == count
    )


def test_missing_observation_is_not_automatically_failure(portal):
    client, _ = portal
    stop(client)
    report = client.get("/api/evaluator/report", headers=headers("evaluator")).json()
    assert report["objectives"][0]["observation"]["status"] == "not_observed"
    assert report["objectives"][0]["judgment"] is None
    assert report["objectives"][1]["observation"]["status"] == "human_review_required"
    assert report["aggregate_score"] is None


def test_offline_report_survives_reset_and_feedback_has_no_staff_text(portal):
    client, service = portal
    stop(client)
    assert (
        client.get(
            "/api/participant/feedback", headers=headers("soc_analyst")
        ).status_code
        == 409
    )
    secret_text = "PRIVATE_STAFF_TEXT secret-password-example /private/server/path"
    for index in range(1, 6):
        assert (
            post(
                client,
                judgment(
                    f"LO{index}",
                    rationale=secret_text,
                    improvement_actions=[
                        {
                            "description": "Validate telemetry availability",
                            "owner": "Patrick",
                            "priority": "high",
                            "target_date": "Before rehearsal",
                        }
                    ],
                ),
            ).status_code
            == 200
        )
    bundle = client.get(
        "/api/evaluator/exports/bundle.json", headers=headers("evaluator")
    ).json()
    live = client.get("/api/evaluator/report", headers=headers("evaluator")).json()
    assert live == build_report(bundle)
    assert live["status"] == "reviewed" and len(live["improvement_actions"]) == 5
    markdown = client.get("/api/evaluator/exports/aar.md", headers=headers("evaluator"))
    assert markdown.text == render_markdown(live)
    feedback = client.get("/api/participant/feedback", headers=headers("soc_analyst"))
    assert feedback.json() == participant_feedback(live)
    for forbidden in (
        secret_text,
        "evaluator_id",
        "evidence_ids",
        "checkpoint_path",
        "checks",
        "rationale",
    ):
        assert forbidden not in feedback.text
    assert (
        client.get(
            "/api/participant/feedback", headers=headers("evaluator")
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/facilitator/reset",
            headers=headers("facilitator"),
            json={"new_run_id": "fresh-aar-run"},
        ).status_code
        == 200
    )
    fresh = client.get("/api/evaluator/report", headers=headers("evaluator")).json()
    assert fresh["reviewed_objectives"] == 0
    assert build_report(bundle) == live
    assert post(client, judgment()).status_code == 409


def test_two_evaluators_cannot_silently_overwrite_each_other(portal):
    client, service = portal
    stop(client)

    def submit(actor):
        try:
            return service.judge_objective(
                PortalPrincipal(actor, "evaluator"),
                {key: value for key, value in judgment().items() if key != "run_id"},
                run_id="aar-api-run",
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ("evaluator-one", "evaluator-two")))
    assert sum(result is not None for result in results) == 1
    assert service.aar_report()["reviewed_objectives"] == 1


def test_review_shell_is_public_but_has_no_embedded_run_data(portal):
    client, _ = portal
    page = client.get("/evaluator")
    assert page.status_code == 200
    assert "aar-api-run" not in page.text
    assert "unsafe-inline" not in page.headers["content-security-policy"]
    assert "Record a judgment" in page.text


def timeline_payload(service):
    principal = PortalPrincipal("actor-soc_analyst", "soc_analyst")
    signals = service.participant_evidence(principal)["signals"]
    assert len(signals) >= 6
    return {
        "run_id": service.run.run_id,
        "entries": [
            {
                "occurred_at": signal["timestamp"],
                "event_id": signal["event_id"],
                "statement_type": "fact" if index % 2 else "inference",
                "summary": "Learner timeline statement",
            }
            for index, signal in enumerate(signals[:6])
        ],
    }


def test_learner_timeline_is_retained_for_human_review_without_answer_key(portal):
    client, service = portal
    client.post("/api/facilitator/prepare", headers=headers("facilitator"))
    client.post("/api/facilitator/start", headers=headers("facilitator"))
    client.post(
        "/api/facilitator/advance",
        headers=headers("facilitator"),
        json={"elapsed_seconds": 300},
    )
    payload = timeline_payload(service)
    response = client.post(
        "/api/participant/timeline", headers=headers("soc_analyst"), json=payload
    )
    assert response.status_code == 200
    assert set(response.json()) == {"submission_id", "run_id", "status"}
    submission = service.store.submissions(service.run.run_id)[-1]
    for actual, expected in zip(submission["payload"]["entries"], payload["entries"]):
        assert datetime.fromisoformat(
            actual["occurred_at"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(expected["occurred_at"].replace("Z", "+00:00"))
        assert {
            key: value for key, value in actual.items() if key != "occurred_at"
        } == {key: value for key, value in expected.items() if key != "occurred_at"}
    assert submission["payload"]["elapsed_seconds"] == 300
    assert submission["result"]["quality_requires_evaluator"] is True
    assert service.aar_report()["objectives"][1]["judgment"] is None


@pytest.mark.parametrize(
    "invalid",
    [
        "foreign_event",
        "duplicate",
        "too_few",
        "no_timezone",
        "forged_source",
        "staff_event",
        "wrong_run",
    ],
)
def test_timeline_rejects_hidden_foreign_and_malformed_evidence(portal, invalid):
    client, service = portal
    client.post("/api/facilitator/prepare", headers=headers("facilitator"))
    client.post("/api/facilitator/start", headers=headers("facilitator"))
    client.post(
        "/api/facilitator/advance",
        headers=headers("facilitator"),
        json={"elapsed_seconds": 300},
    )
    payload = timeline_payload(service)
    if invalid == "foreign_event":
        payload["entries"][0]["event_id"] = "foreign"
    elif invalid == "duplicate":
        payload["entries"][1]["event_id"] = payload["entries"][0]["event_id"]
    elif invalid == "too_few":
        payload["entries"].pop()
    elif invalid == "no_timezone":
        payload["entries"][0]["occurred_at"] = "2026-10-02T12:00:00"
    elif invalid == "forged_source":
        payload["entries"][0]["source"] = "helpdesk"
    elif invalid == "staff_event":
        events = service.store.events(
            service.run.definition.exercise_id, service.run.run_id
        )
        payload["entries"][0]["event_id"] = next(
            event["event_id"]
            for event in events
            if event["visibility"] == "facilitator"
        )
    else:
        payload["run_id"] = "old-run"
    response = client.post(
        "/api/participant/timeline", headers=headers("soc_analyst"), json=payload
    )
    assert response.status_code in {409, 422}
    assert not service.store.submissions(service.run.run_id)


def test_timeline_unavailable_to_staff_and_after_containment_checkpoint(portal):
    client, service = portal
    client.post("/api/facilitator/prepare", headers=headers("facilitator"))
    client.post("/api/facilitator/start", headers=headers("facilitator"))
    payload = timeline_payload(service)
    assert (
        client.post(
            "/api/participant/timeline", headers=headers("evaluator"), json=payload
        ).status_code
        == 403
    )
    deadline = next(
        item.trigger.seconds
        for item in service.run.definition.items
        if item.item_id == "DP2"
    )
    client.post(
        "/api/facilitator/advance",
        headers=headers("facilitator"),
        json={"elapsed_seconds": deadline + 1},
    )
    assert (
        client.post(
            "/api/participant/timeline", headers=headers("soc_analyst"), json=payload
        ).status_code
        == 409
    )
