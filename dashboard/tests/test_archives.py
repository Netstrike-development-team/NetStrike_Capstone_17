"""Historical staff review snapshots, reset capture and atomic failure handling."""

from __future__ import annotations

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard import archive
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.aar import build_report, render_markdown
from orchestrator.evidence import render_jsonl

TOKENS = {
    role: f"archive-{role}-token-at-least-24-characters"
    for role in (
        "facilitator",
        "evaluator",
        "technical_operator",
        "soc_analyst",
        "simulated_user",
        "identity_capture_service",
    )
}
STAFF = PortalPrincipal("actor-facilitator", "facilitator")
EVALUATOR = PortalPrincipal("actor-evaluator", "evaluator")


def headers(role="facilitator"):
    return {"Authorization": f"Bearer {TOKENS[role]}"}


def app(service):
    return create_app(
        service,
        TokenAuthenticator(
            {
                token: PortalPrincipal("actor-" + role, role)
                for role, token in TOKENS.items()
            }
        ),
        sso_allowed_origins={"http://testserver"},
    )


@pytest.fixture
def portal(tmp_path):
    store = PortalStore(tmp_path / "portal.sqlite3")
    service = PortalService(store, run_id="archive-current")
    with TestClient(app(service)) as client:
        yield client, service
    store.close()


def stop(client):
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    assert (
        client.post(
            "/api/facilitator/stop",
            headers=headers(),
            json={"reason": "Stopped partial play for archive testing"},
        ).status_code
        == 200
    )


def events(service, run_id=None):
    return service.store.events(
        service.run.definition.exercise_id, run_id or service.run.run_id
    )


def capture(client, service, *, auth_role="evaluator", **overrides):
    payload = {
        "run_id": service.run.run_id,
        "expected_bundle_sha256": service.aar_bundle()["content_sha256"],
        **overrides,
    }
    return client.post(
        "/api/evaluator/archives", headers=headers(auth_role), json=payload
    )


def get(client, identifier, suffix="report", role="evaluator"):
    return client.get(
        f"/api/evaluator/archives/{identifier}/{suffix}", headers=headers(role)
    )


def judgment(service, objective="LO1", revision=0):
    return service.judge_objective(
        EVALUATOR,
        {
            "objective_id": objective,
            "rating": "not_observed",
            "rationale": "Private staff analysis of the platform fault.",
            "evidence_ids": [],
            "expected_revision": revision,
            "override_reason": "Clarified the earlier assessment." if revision else "",
            "platform_reason": "Partial play stopped before objective observation.",
            "improvement_actions": [
                {
                    "description": "Retest the source",
                    "owner": "Patrick",
                    "priority": "high",
                    "target_date": "Next rehearsal",
                }
            ],
        },
        run_id=service.run.run_id,
    )


def test_reset_retains_review_history_and_submissions_without_new_run_leaks(portal):
    client, service = portal
    assert client.post("/api/facilitator/start", headers=headers()).status_code == 200
    signals = service.participant_evidence(PortalPrincipal("analyst", "soc_analyst"))[
        "signals"
    ]
    assert len(signals) >= 6
    assert (
        client.post(
            "/api/participant/timeline",
            headers=headers("soc_analyst"),
            json={
                "run_id": service.run.run_id,
                "entries": [
                    {
                        "occurred_at": event["timestamp"],
                        "statement_type": "fact",
                        "event_id": event["event_id"],
                        "summary": "Synthetic sourced observation",
                    }
                    for event in sorted(signals[:6], key=lambda item: item["timestamp"])
                ],
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/facilitator/stop", headers=headers(), json={"reason": "Partial play"}
        ).status_code
        == 200
    )
    judgment(service)
    judgment(service, revision=1)
    before = service.aar_bundle()
    reset = client.post(
        "/api/facilitator/reset", headers=headers(), json={"new_run_id": "archive-next"}
    )
    assert reset.status_code == 200
    identifier = reset.json()["reset"]["review_archive_id"]
    archived = get(client, identifier, "bundle.json").json()
    assert archived == before
    report = get(client, identifier).json()
    assert len(report["objectives"][0]["history"]) == 2
    assert len(report["submissions"]) == 1
    assert report["status"] == "provisional" and report["aggregate_score"] is None
    listing = client.get("/api/evaluator/archives", headers=headers("evaluator")).json()
    record = listing["archives"][0]
    assert record["archive_id"] == identifier and record["run_id"] == "archive-current"
    assert record["capture_reason"] == "application_reset"
    assert record["captured_by"] == {"actor_id": STAFF.actor_id, "role": STAFF.role}
    assert record["last_sequence"] == before["events"][-1]["sequence"]
    old_events = events(service, "archive-current")
    assert old_events[-1]["event_type"] == "evaluation.archive.created"
    assert old_events[-1]["sequence"] == record["last_sequence"] + 1
    current = service.aar_bundle()
    assert current["run_id"] == "archive-next" and current["submissions"] == []
    serialized = json.dumps(current) + json.dumps(
        service.participant_evidence(PortalPrincipal("analyst", "soc_analyst"))
    )
    assert (
        "Private staff analysis" not in serialized
        and "evaluation.archive.created" not in serialized
    )
    assert service.readiness()["ready_to_prepare"]


def test_explicit_capture_replays_without_duplicate_events_or_changed_attribution(
    portal,
):
    client, service = portal
    stop(client)
    bundle = service.aar_bundle()
    first = capture(client, service)
    assert first.status_code == 200 and first.json()["status"] == "captured"
    after = events(service)
    second = capture(
        client,
        service,
        auth_role="facilitator",
        expected_bundle_sha256=bundle["content_sha256"],
    )
    assert second.status_code == 200 and second.json()["status"] == "already_captured"
    assert (
        first.json()["metadata"]["archive_id"]
        == second.json()["metadata"]["archive_id"]
    )
    assert second.json()["metadata"]["captured_by"]["role"] == "evaluator"
    assert events(service) == after
    assert len(service.review_archives()["archives"]) == 1


def test_capture_cas_and_stale_run_are_checked_before_writes(portal):
    client, service = portal
    stop(client)
    digest = service.aar_bundle()["content_sha256"]
    judgment(service)
    before = events(service)
    assert capture(client, service, expected_bundle_sha256=digest).status_code == 409
    assert capture(client, service, run_id="some-old-run").status_code == 409
    assert events(service) == before and service.review_archives()["archives"] == []


@pytest.mark.parametrize("state", ["ready", "running", "paused"])
def test_capture_and_reset_refuse_nonterminal_play(portal, state):
    client, service = portal
    if state != "ready":
        client.post("/api/facilitator/start", headers=headers())
    if state == "paused":
        client.post("/api/facilitator/pause", headers=headers())
    before = events(service)
    assert capture(client, service).status_code == 409
    assert (
        client.post(
            "/api/facilitator/reset", headers=headers(), json={"new_run_id": "no-reset"}
        ).status_code
        == 409
    )
    assert events(service) == before and service.review_archives()["archives"] == []


@pytest.mark.parametrize("role", list(TOKENS))
def test_capture_listing_and_all_downloads_enforce_review_roles(portal, role):
    client, service = portal
    stop(client)
    identifier = capture(client, service).json()["metadata"]["archive_id"]
    expected = 200 if role in {"facilitator", "evaluator"} else 403
    assert (
        client.get("/api/evaluator/archives", headers=headers(role)).status_code
        == expected
    )
    assert capture(client, service, auth_role=role).status_code == expected
    for suffix in ("bundle.json", "report", "aar.md", "events.jsonl"):
        response = get(client, identifier, suffix, role)
        assert response.status_code == expected
        if expected == 200:
            assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/evaluator/archives").status_code == 401
    assert client.post("/api/evaluator/archives", json={}).status_code == 401


def test_technical_operator_reset_captures_without_granting_archive_read_access(portal):
    client, service = portal
    stop(client)
    response = client.post(
        "/api/facilitator/reset",
        headers=headers("technical_operator"),
        json={"new_run_id": "operator-reset"},
    )
    assert response.status_code == 200
    identifier = response.json()["reset"]["review_archive_id"]
    record = service.review_archive(identifier)["metadata"]
    assert record["captured_by"]["role"] == "technical_operator"
    assert get(client, identifier, role="technical_operator").status_code == 403


def test_internal_cli_reset_is_attributed_to_system_not_invented_staff(portal):
    client, service = portal
    stop(client)
    result = service.reset_run(new_run_id="internal-reset")
    record = service.review_archive(result["reset"]["review_archive_id"])["metadata"]
    assert record["captured_by"] == {"actor_id": "application-reset", "role": "system"}


def test_downloads_reproduce_the_frozen_bundle_and_are_read_only(portal, monkeypatch):
    client, service = portal
    stop(client)
    before = service.aar_bundle()
    identifier = capture(client, service).json()["metadata"]["archive_id"]
    ledger = events(service)
    sequence = service.run.sequencer.sequence

    def forbidden(*_args, **_kwargs):
        raise AssertionError("archive read attempted simulation or writes")

    monkeypatch.setattr(service.run.controller, "start", forbidden)
    monkeypatch.setattr(service.store, "append_event", forbidden)
    monkeypatch.setattr(service.store, "append_review_archive", forbidden)
    assert get(client, identifier, "bundle.json").json() == before
    assert get(client, identifier, "aar.md").text == render_markdown(
        build_report(before)
    )
    assert get(client, identifier, "events.jsonl").text == render_jsonl(
        before["events"]
    )
    assert get(client, identifier).json() == build_report(before)
    assert events(service) == ledger and service.run.sequencer.sequence == sequence
    assert "Private staff analysis" not in json.dumps(service.review_archives())


def test_archives_survive_database_reopen_without_runtime_resume(tmp_path, monkeypatch):
    # Module CI and installed consumers need not run from the repository root.
    monkeypatch.chdir(tmp_path)
    cloud_scenario = (
        Path(__file__).resolve().parents[2] / "orchestrator/scenarios/cloud-slice.v1.json"
    )
    path = tmp_path / "portal.sqlite3"
    store = PortalStore(path)
    service = PortalService(store, run_id="before-restart")
    service.start_run(STAFF)
    service.run.fail_safe_stop("archive persistence")
    digest = service.aar_bundle()["content_sha256"]
    identifier = service.capture_review_archive(
        EVALUATOR, run_id=service.run.run_id, expected_bundle_sha256=digest
    )["metadata"]["archive_id"]
    frozen = service.review_archive(identifier)
    store.close()
    reopened = PortalStore(path)
    fresh = PortalService(
        reopened,
        run_id="after-restart",
        scenario_path=str(cloud_scenario),
    )
    try:
        assert fresh.review_archive(identifier) == frozen
        assert (
            fresh.aar_bundle()["checkpoint_ids"] != frozen["bundle"]["checkpoint_ids"]
        )
        assert fresh.run.controller.state.value == "ready"
        assert fresh.readiness()["ready_to_prepare"]
    finally:
        reopened.close()


def test_oversized_capture_blocks_reset_and_cancels_reserved_sequence(
    portal, monkeypatch
):
    client, service = portal
    stop(client)
    assert archive.MAX_BYTES == 20 * 1024 * 1024
    before = events(service)
    sequence = service.run.sequencer.sequence
    monkeypatch.setattr(archive, "MAX_BYTES", 1)
    assert capture(client, service).status_code == 409
    response = client.post(
        "/api/facilitator/reset",
        headers=headers(),
        json={"new_run_id": "oversized-reset"},
    )
    assert response.status_code == 409
    assert events(service) == before and service.run.sequencer.sequence == sequence
    assert service.run.run_id == "archive-current"
    assert service.review_archives()["archives"] == []


def test_oversized_stored_bundle_is_refused_before_json_decode(portal, monkeypatch):
    client, service = portal
    stop(client)
    identifier = capture(client, service).json()["metadata"]["archive_id"]
    monkeypatch.setattr("dashboard.store.MAX_BYTES", 1)
    assert get(client, identifier, "bundle.json").status_code == 409
    assert client.get("/api/evaluator/archives", headers=headers()).status_code == 409


def test_bounded_pagination_is_capture_order_and_metadata_only(portal):
    client, service = portal
    stop(client)
    identifiers = [
        capture(client, service).json()["metadata"]["archive_id"] for _ in range(3)
    ]
    first = client.get("/api/evaluator/archives?limit=2", headers=headers("evaluator"))
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    page = first.json()
    assert [item["archive_id"] for item in page["archives"]] == identifiers[:2]
    assert page["has_more"] and all(
        "bundle" not in item and "report" not in item for item in page["archives"]
    )
    second = client.get(
        f"/api/evaluator/archives?limit=2&after_sequence={page['next_sequence']}",
        headers=headers("evaluator"),
    ).json()
    assert [item["archive_id"] for item in second["archives"]] == identifiers[2:]
    assert not second["has_more"]
    for query in ("limit=0", "limit=101", "after_sequence=-1"):
        assert (
            client.get(
                "/api/evaluator/archives?" + query, headers=headers("evaluator")
            ).status_code
            == 422
        )


def test_unknown_and_cross_exercise_ids_do_not_disclose_archives(portal):
    client, service = portal
    stop(client)
    identifier = capture(client, service).json()["metadata"]["archive_id"]
    assert get(client, str(uuid.uuid4())).status_code == 404
    assert get(client, "not-a-uuid").status_code == 409
    assert service.store.review_archive("different-exercise", identifier) is None
    assert service.store.review_archives("different-exercise")["archives"] == []
    assert service.store.review_archive("x' OR 1=1 --", identifier) is None


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_sqlite_guards_reject_archive_mutation_or_deletion(portal, operation):
    client, service = portal
    stop(client)
    identifier = capture(client, service).json()["metadata"]["archive_id"]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with service.store._connection:
            service.store._connection.execute(
                "UPDATE review_archives SET metadata = '{}'"
                if operation == "UPDATE"
                else "DELETE FROM review_archives"
            )
    assert get(client, identifier).status_code == 200


@pytest.mark.parametrize("mutation", ["bundle", "metadata", "audit", "missing_audit"])
def test_corrupt_stored_archives_are_rejected_on_download_and_listing(portal, mutation):
    client, service = portal
    stop(client)
    record = capture(client, service).json()["metadata"]
    db = service.store._connection
    with db:
        if mutation in {"bundle", "metadata"}:
            db.execute(
                "DROP TRIGGER review_archives_no_update"
            )  # Simulate external DB corruption.
            column = "bundle" if mutation == "bundle" else "metadata"
            db.execute(f"UPDATE review_archives SET {column} = ?", ("{}",))
        elif mutation == "audit":
            db.execute(
                "UPDATE events SET payload = '{}' WHERE event_id = ?",
                (record["audit_event_id"],),
            )
        else:
            db.execute(
                "DELETE FROM events WHERE event_id = ?", (record["audit_event_id"],)
            )
    assert get(client, record["archive_id"]).status_code == 409
    assert (
        client.get("/api/evaluator/archives", headers=headers("evaluator")).status_code
        == 409
    )


def test_archive_and_audit_rollback_together_and_reset_can_retry(portal):
    client, service = portal
    stop(client)
    before = events(service)
    sequence = service.run.sequencer.sequence
    with service.store._connection:
        service.store._connection.execute("""CREATE TRIGGER injected_archive_failure
            BEFORE INSERT ON events WHEN NEW.payload LIKE '%evaluation.archive.created%'
            BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END;""")
    failed = client.post(
        "/api/facilitator/reset",
        headers=headers(),
        json={"new_run_id": "not-yet-reset"},
    )
    assert failed.status_code == 409
    assert (
        service.run.run_id == "archive-current"
        and service.run.controller.state.value == "stopped"
    )
    assert service.review_archives()["archives"] == [] and events(service) == before
    assert service.run.sequencer.sequence == sequence
    with service.store._connection:
        service.store._connection.execute("DROP TRIGGER injected_archive_failure")
    retried = client.post(
        "/api/facilitator/reset",
        headers=headers(),
        json={"new_run_id": "not-yet-reset"},
    )
    assert retried.status_code == 200
    assert len(service.review_archives()["archives"]) == 1
    old = events(service, "archive-current")
    assert [item["sequence"] for item in old] == list(range(1, len(old) + 1))


def test_validation_failure_or_invalid_reset_target_preserves_the_old_run(
    portal, monkeypatch
):
    client, service = portal
    stop(client)
    before = events(service)
    assert (
        client.post(
            "/api/facilitator/reset",
            headers=headers(),
            json={"new_run_id": "archive-current"},
        ).status_code
        == 409
    )
    assert not service.review_archives()["archives"]

    def invalid():
        raise ValueError("invalid frozen evidence")

    monkeypatch.setattr(service, "aar_bundle", invalid)
    assert (
        client.post(
            "/api/facilitator/reset",
            headers=headers(),
            json={"new_run_id": "must-not-reset"},
        ).status_code
        == 409
    )
    assert events(service) == before and service.run.run_id == "archive-current"


def test_concurrent_exact_captures_have_one_snapshot_and_one_audit(portal):
    client, service = portal
    stop(client)
    payload = {
        "run_id": service.run.run_id,
        "expected_bundle_sha256": service.aar_bundle()["content_sha256"],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda principal: service.capture_review_archive(principal, **payload),
                [STAFF, EVALUATOR],
            )
        )
    assert {item["status"] for item in results} == {"captured", "already_captured"}
    assert len({item["metadata"]["archive_id"] for item in results}) == 1
    assert (
        len(
            [
                event
                for event in events(service)
                if event["event_type"] == "evaluation.archive.created"
            ]
        )
        == 1
    )


def test_snapshot_does_not_change_when_later_reviews_are_recorded(portal):
    client, service = portal
    stop(client)
    first = capture(client, service).json()["metadata"]["archive_id"]
    frozen = deepcopy(service.review_archive(first))
    for objective in ("LO1", "LO2", "LO3", "LO4", "LO5"):
        judgment(service, objective)
    second = capture(client, service).json()["metadata"]["archive_id"]
    assert first != second and service.review_archive(first) == frozen
    assert get(client, first).json()["status"] == "provisional"
    reviewed = get(client, second).json()
    assert reviewed["status"] == "reviewed" and reviewed["reviewed_objectives"] == 5
    assert reviewed["run_state"] == "stopped" and reviewed["aggregate_score"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_bundle_sha256": "bad"},
        {"expected_bundle_sha256": None},
        {"actor_id": "forged"},
        {"role": "facilitator"},
        {"path": "/outside"},
    ],
)
def test_capture_input_cannot_forge_actor_or_expand_scope(portal, payload):
    client, service = portal
    stop(client)
    assert capture(client, service, **payload).status_code == 422
    assert service.review_archives()["archives"] == []


def test_old_capture_request_cannot_write_into_new_run_after_reset(portal):
    client, service = portal
    stop(client)
    run_id = service.run.run_id
    digest = service.aar_bundle()["content_sha256"]
    client.post(
        "/api/facilitator/reset",
        headers=headers(),
        json={"new_run_id": "archive-fresh"},
    )
    before = events(service)
    assert (
        capture(
            client, service, run_id=run_id, expected_bundle_sha256=digest
        ).status_code
        == 409
    )
    assert events(service) == before
