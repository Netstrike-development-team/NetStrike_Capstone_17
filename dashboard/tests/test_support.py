"""Human support privacy, audit, bounded retries, reset and portable AAR evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import threading
import asyncio

import pytest
from fastapi.testclient import TestClient

from dashboard.app import MAX_SUPPORT_BYTES, SupportRequestInput, create_app, support_input
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from dashboard import support_demo
from dashboard.event_spool import export
from orchestrator.aar import _digest, build_report, render_markdown, validate_bundle
from orchestrator.controller import ControllerError, RunState
from orchestrator.support import LEARNER_ROLES, support_index
from shared.events import EventValidator
from starlette.requests import Request
from fastapi import HTTPException

STAFF = PortalPrincipal("support-staff", "facilitator")
TECH = PortalPrincipal("support-tech", "technical_operator")
OBSERVER = PortalPrincipal("support-observer", "evaluator")
LEARNER = PortalPrincipal("support-learner", "soc_analyst")
OTHER = PortalPrincipal("support-other", "identity_responder")
ROLES = sorted(LEARNER_ROLES) + ["facilitator", "technical_operator", "evaluator",
                               "simulated_user", "identity_capture_service"]
TOKENS = {role: "support-api-" + role + "-at-least-24-characters" for role in ROLES}


@pytest.fixture
def runtime(tmp_path):
    store = PortalStore(tmp_path / "portal.sqlite3")
    service = PortalService(store, run_id="support-run")
    yield service
    store.close()


def start(service):
    service.start_run(STAFF)


def request(service, principal=LEARNER, **overrides):
    payload = {"run_id": service.run.run_id, "idempotency_key": "question-1",
               "objective_id": "LO2", "message": "How do we distinguish fact from inference?"}
    return service.support.request(principal, **(payload | overrides))


def reply(service, question, principal=STAFF, **overrides):
    payload = {"run_id": service.run.run_id, "request_id": question["request_id"],
               "idempotency_key": "reply-1", "kind": "clarification", "objective_ids": ["LO2"],
               "message": "Label interpretations as inference and cite artifacts for observed facts."}
    return service.support.respond(principal, **(payload | overrides))


def events(service, run_id=None):
    return service.store.events(service.run.definition.exercise_id, run_id or service.run.run_id)


def headers(role="facilitator"):
    return {"Authorization": "Bearer " + TOKENS[role]}


@pytest.fixture
def portal(runtime):
    auth = TokenAuthenticator({token: PortalPrincipal("actor-" + role, role)
                               for role, token in TOKENS.items()})
    with TestClient(create_app(runtime, auth, sso_allowed_origins={"http://testserver"})) as client:
        yield client, runtime


def test_attributed_reply_private_projection_and_no_automatic_grade(runtime):
    start(runtime)
    question = request(runtime)
    response = reply(runtime, question, kind="hint", objective_ids=["LO3", "LO2"])
    own = runtime.support.view(LEARNER)["requests"]
    assert len(own) == 1 and own[0]["response"]["kind"] == "hint"
    assert "responder_id" not in own[0]["response"] and "requester_id" not in own[0]
    assert runtime.support.view(OTHER)["requests"] == []
    assert "question" not in json.dumps(runtime.participant_state())
    assert not any(signal["event_type"].startswith("exercise.support.")
                   for signal in runtime.participant_evidence(OTHER)["signals"])
    staff = runtime.support.view(OBSERVER, staff=True)["requests"]
    assert staff[0]["requester_id"] == LEARNER.actor_id
    assert staff[0]["response"]["responder_id"] == STAFF.actor_id
    assert staff[0]["response"]["event_id"] == response["event_id"]
    report = runtime.aar_report()
    assert report["support_requests"] == staff
    assert report["reviewed_objectives"] == 0 and report["status"] == "provisional"
    assert all(item["judgment"] is None for item in report["objectives"])
    assert runtime.run.controller.checkpoint_results == {}
    for event in events(runtime):
        EventValidator().validate(event)
    assert [event["sequence"] for event in events(runtime)] == list(range(1, len(events(runtime)) + 1))
    assert question["event_id"] != response["event_id"]


@pytest.mark.parametrize("role", ROLES)
def test_api_role_boundaries_and_no_store_read(portal, role):
    client, service = portal
    start(service)
    expected = 200 if role in LEARNER_ROLES else 403
    before = events(service)
    read = client.get("/api/participant/support", headers=headers(role))
    assert read.status_code == expected
    if expected == 200:
        assert read.headers["cache-control"] == "no-store"
    staff = client.get("/api/facilitator/support", headers=headers(role))
    assert staff.status_code == (200 if role in {"facilitator", "technical_operator", "evaluator"} else 403)
    if staff.status_code == 200:
        assert staff.headers["cache-control"] == "no-store"
    assert events(service) == before
    assert client.get("/api/participant/support").status_code == 401
    post = client.post("/api/participant/support", headers=headers(role), json={
        "run_id": service.run.run_id, "idempotency_key": "api-request",
        "objective_id": "LO1", "message": "Please clarify the task.",
    })
    assert post.status_code == expected
    if role not in {"facilitator", "technical_operator"}:
        assert client.post("/api/facilitator/support/replies", headers=headers(role), json={
            "run_id": service.run.run_id, "request_id": "untrusted", "idempotency_key": "x",
            "kind": "hint", "message": "unauthorized", "objective_ids": ["LO1"],
        }).status_code == 403


def test_api_request_reply_and_spoofing_forbidden(portal):
    client, service = portal
    start(service)
    payload = {"run_id": service.run.run_id, "idempotency_key": "api-q", "objective_id": "LO1",
               "message": "Please explain the submission format."}
    assert client.post("/api/participant/support", headers=headers("soc_analyst"),
                       json=payload | {"actor_id": "pretend-staff"}).status_code == 422
    question = client.post("/api/participant/support", headers=headers("soc_analyst"), json=payload)
    assert question.status_code == 200
    response = client.post("/api/facilitator/support/replies", headers=headers(), json={
        "run_id": service.run.run_id, "request_id": question.json()["request_id"],
        "idempotency_key": "api-a", "kind": "clarification", "message": "Use artifact identifiers.",
        "objective_ids": ["LO1"],
    })
    assert response.status_code == 200
    own = client.get("/api/participant/support", headers=headers("soc_analyst")).json()
    assert own["requests"][0]["response"]["text"] == "Use artifact identifiers."
    other = client.get("/api/participant/support", headers=headers("identity_responder")).json()
    assert other["requests"] == []


@pytest.mark.parametrize("field,value", [("objective_id", "LO6"), ("message", "   "),
                                       ("message", "x" * 1025), ("message", "a\x00b"),
                                       ("idempotency_key", ""), ("message", True)])
def test_invalid_questions_do_not_reserve_or_write(runtime, field, value):
    start(runtime)
    before = events(runtime)
    with pytest.raises((ValueError, ControllerError)):
        request(runtime, **{field: value})
    assert events(runtime) == before
    assert runtime.run.sequencer.sequence == len(before)


def test_idempotent_retries_and_conflicts(runtime):
    start(runtime)
    first = request(runtime)
    assert request(runtime)["event_id"] == first["event_id"]
    assert request(runtime)["replayed"]
    with pytest.raises(ValueError, match="conflicts"):
        request(runtime, message="Different question with reused key")
    response = reply(runtime, first)
    assert reply(runtime, first)["event_id"] == response["event_id"]
    assert reply(runtime, first)["replayed"]
    with pytest.raises(ValueError, match="conflicts"):
        reply(runtime, first, objective_ids=["LO3"])
    with pytest.raises(ValueError, match="immutable"):
        reply(runtime, first, idempotency_key="new-reply")
    assert len(support_index(events(runtime))) == 1


def test_pending_and_per_actor_bounds(runtime):
    start(runtime)
    question = request(runtime)
    with pytest.raises(ValueError, match="pending"):
        request(runtime, idempotency_key="another")
    reply(runtime, question)
    for index in range(1, 10):
        question = request(runtime, idempotency_key=f"q-{index}")
        reply(runtime, question, idempotency_key=f"a-{index}")
    with pytest.raises(ValueError, match="limit"):
        request(runtime, idempotency_key="q-over-limit")
    assert len(runtime.support.view(LEARNER)["requests"]) == 10


def test_total_run_bounds(runtime):
    start(runtime)
    for index in range(50):
        actor = PortalPrincipal(f"learner-{index}", "soc_analyst")
        question = request(runtime, actor)
        reply(runtime, question, idempotency_key=f"a-{index}")
    with pytest.raises(ValueError, match="limit"):
        request(runtime, PortalPrincipal("one-more", "soc_analyst"))
    assert len(runtime.support.view(STAFF, staff=True)["requests"]) == 50


@pytest.mark.parametrize("state", [RunState.READY, RunState.STOPPED, RunState.COMPLETED])
def test_new_requests_require_live_or_paused_play(runtime, state):
    runtime.run.controller.state = state
    before = events(runtime)
    with pytest.raises(ControllerError, match="running or paused"):
        request(runtime)
    assert events(runtime) == before


def test_paused_communication_and_platform_stop_response(runtime):
    start(runtime)
    runtime.control_run("pause")
    question = request(runtime)
    with pytest.raises(ControllerError, match="not coaching"):
        reply(runtime, question, TECH, kind="hint")
    runtime.clock.fault("driver_failed")
    with pytest.raises(ControllerError, match="stopped-run"):
        reply(runtime, question)
    response = reply(runtime, question, TECH, kind="platform_issue",
                     message="The exercise clock stopped. Preserve your evidence for staff.")
    assert response["status"] == "answered"
    assert runtime.support.view(LEARNER)["requests"][0]["response"]["kind"] == "platform_issue"
    assert runtime.aar_report()["reviewed_objectives"] == 0


def test_direct_service_roles_cannot_bypass_api(runtime):
    start(runtime)
    with pytest.raises(ControllerError):
        request(runtime, STAFF)
    question = request(runtime)
    for principal in (LEARNER, OBSERVER):
        with pytest.raises(ControllerError):
            reply(runtime, question, principal)
    with pytest.raises(ControllerError):
        runtime.support.view(LEARNER, staff=True)


def test_single_winner_concurrent_requests_and_replies(runtime):
    start(runtime)

    def ask(index):
        try:
            return request(runtime, idempotency_key=f"ask-{index}")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(ask, range(6)))
    question = next(result for result in results if result)
    assert sum(result is not None for result in results) == 1

    def answer(index):
        try:
            return reply(runtime, question, idempotency_key=f"answer-{index}")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(answer, range(6)))
    assert sum(result is not None for result in results) == 1
    assert [event["sequence"] for event in events(runtime)] == list(range(1, len(events(runtime)) + 1))


def test_reset_preserves_private_archive_and_rejects_stale_requests(runtime, tmp_path):
    start(runtime)
    question = request(runtime)
    reply(runtime, question, kind="hint")
    old_run = runtime.run.run_id
    runtime.stop_run("partial support test", STAFF)
    reset = runtime.reset_run(new_run_id="support-new-run", principal=STAFF)
    archive = runtime.review_archive(reset["reset"]["review_archive_id"])
    assert archive["report"]["support_requests"][0]["response"]["kind"] == "hint"
    assert archive["report"]["reviewed_objectives"] == 0
    assert runtime.support.view(LEARNER)["requests"] == []
    before = events(runtime)
    with pytest.raises(ValueError, match="run changed"):
        request(runtime, run_id=old_run)
    with pytest.raises(ValueError, match="run changed"):
        reply(runtime, question, run_id=old_run)
    assert events(runtime) == before
    published = export(runtime.store.path, tmp_path / "private-spool",
                       exercise_id=runtime.run.definition.exercise_id, execute=True)
    assert published["events_selected"] > 0
    exported = [json.loads(line) for path in (tmp_path / "private-spool").glob("batch-*/events.jsonl")
                for line in path.read_text().splitlines()]
    support = [event for event in exported if event["source"]["component"] == "exercise-support"]
    assert len(support) == 2
    assert all(event["visibility"] == "facilitator" and event["run_id"] == old_run for event in support)
    assert support[1]["correlation_ids"] == [question["request_id"]]


def test_support_evidence_can_be_cited_but_reviewed_feedback_contains_no_support_prose(runtime):
    start(runtime)
    question = request(runtime, message="Private learner question")
    response = reply(runtime, question, kind="platform_issue", message="Private platform explanation")
    runtime.stop_run("intentionally partial review test", STAFF)
    for number in range(1, 6):
        payload = {
            "objective_id": f"LO{number}", "rating": "not_observed",
            "rationale": "Stopped developer test; no learner performance asserted.",
            "evidence_ids": [response["event_id"]], "expected_revision": 0,
            "override_reason": "", "platform_reason": "Deliberately stopped synthetic test",
            "improvement_actions": [],
        }
        runtime.judge_objective(OBSERVER, payload, run_id=runtime.run.run_id)
    assert runtime.aar_report()["status"] == "reviewed"
    feedback = json.dumps(runtime.participant_feedback())
    assert "Private learner question" not in feedback
    assert "Private platform explanation" not in feedback
    assert "support_requests" not in feedback


def test_new_run_cannot_reply_to_an_old_request_even_with_current_run_id(runtime):
    start(runtime)
    question = request(runtime)
    runtime.stop_run("old request test", STAFF)
    runtime.reset_run(new_run_id="fresh-support-run")
    start(runtime)
    before = events(runtime)
    with pytest.raises(ValueError, match="current run"):
        reply(runtime, question)
    assert events(runtime) == before


@pytest.mark.parametrize("failure", [sqlite3.OperationalError, RuntimeError])
def test_write_failure_yields_no_false_ack_and_stops_play(runtime, monkeypatch, failure):
    start(runtime)

    def broken(_event):
        raise failure("private-database-error")

    monkeypatch.setattr(runtime.store, "append_event", broken)
    with pytest.raises(ControllerError, match="evidence unavailable") as error:
        request(runtime)
    assert "private-database-error" not in str(error.value)
    assert runtime.run.controller.state == RunState.STOPPED
    assert runtime.support.view(LEARNER)["requests"] == []
    assert not runtime.readiness()["ready_to_start"]
    with pytest.raises(ValueError):
        runtime.reset_run(new_run_id="must-preserve-gap")


def test_event_construction_failure_after_sequence_allocation_stops_safely(runtime):
    start(runtime)
    misconfigured = PortalPrincipal("x" * 257, "soc_analyst")
    with pytest.raises(ControllerError, match="evidence unavailable"):
        request(runtime, misconfigured)
    assert runtime.run.controller.state == RunState.STOPPED
    assert runtime.support.view(LEARNER)["requests"] == []


def test_post_commit_failure_recovers_same_request_without_duplicates(runtime, monkeypatch):
    start(runtime)
    original = runtime.store.append_event

    def ambiguous(event):
        original(event)
        raise OSError("lost acknowledgement after persistence")

    monkeypatch.setattr(runtime.store, "append_event", ambiguous)
    with pytest.raises(ControllerError):
        request(runtime)
    assert runtime.run.controller.state == RunState.STOPPED
    retry = request(runtime)
    assert retry["replayed"]
    assert len(runtime.support.view(LEARNER)["requests"]) == 1
    assert len(support_index(events(runtime))) == 1


def test_response_failure_never_releases_an_unaudited_reply(runtime, monkeypatch):
    start(runtime)
    question = request(runtime)

    def broken(_event):
        raise OSError("staff answer could not be saved")

    monkeypatch.setattr(runtime.store, "append_event", broken)
    with pytest.raises(ControllerError):
        reply(runtime, question)
    assert runtime.support.view(LEARNER)["requests"][0]["response"] is None
    assert runtime.run.controller.state == RunState.STOPPED


def test_reset_and_support_write_are_serialized(runtime, monkeypatch):
    start(runtime)
    question = request(runtime)
    runtime.stop_run("platform investigation", STAFF)
    entered, release = threading.Event(), threading.Event()
    original = runtime.store.append_event

    def held(event):
        if event["event_type"] == "exercise.support.responded":
            entered.set()
            assert release.wait(5)
        return original(event)

    monkeypatch.setattr(runtime.store, "append_event", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        answering = pool.submit(reply, runtime, question, TECH, kind="platform_issue")
        assert entered.wait(5)
        resetting = pool.submit(runtime.reset_run, new_run_id="after-held-answer")
        assert not resetting.done()
        release.set()
        assert answering.result(timeout=5)["run_id"] == "support-run"
        state = resetting.result(timeout=5)
    archived = runtime.review_archive(state["reset"]["review_archive_id"])
    assert archived["report"]["support_requests"][0]["response"]["kind"] == "platform_issue"
    assert runtime.support.view(LEARNER)["requests"] == []


@pytest.mark.parametrize("payload", [b"broken-private-input", b"[]", b'{"message":"private"}'])
def test_bad_api_input_does_not_echo_free_text_or_write(portal, payload):
    client, service = portal
    start(service)
    before = events(service)
    response = client.post("/api/participant/support", headers=headers("soc_analyst"), content=payload)
    assert response.status_code == 422
    assert "private" not in response.text
    assert events(service) == before


def test_stream_limit_stops_before_reading_unbounded_body():
    read = []

    async def receive():
        read.append(True)
        return {"type": "http.request", "body": b"x" * (MAX_SUPPORT_BYTES + 1), "more_body": True}

    request_object = Request({"type": "http", "method": "POST", "headers": []}, receive)
    with pytest.raises(HTTPException) as error:
        asyncio.run(support_input(request_object, SupportRequestInput))
    assert error.value.status_code == 413
    assert len(read) == 1


def test_markdown_escapes_human_text_and_request_is_not_proof_of_support(runtime):
    start(runtime)
    request(runtime, message="<script>bad()</script> [link](javascript:bad) **question**")
    report = runtime.aar_report()
    rendered = render_markdown(report)
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "No staff reply recorded" in rendered
    assert "not automatic objective ratings" in rendered


@pytest.mark.parametrize("change", ["staff_role", "public_visibility", "foreign_source", "missing_request",
                                    "duplicate_reply", "objective", "reply_clock", "dry_run", "retry_key"])
def test_tampered_support_cannot_be_resigned_into_a_valid_archive(runtime, change):
    start(runtime)
    question = request(runtime)
    reply(runtime, question)
    bundle = deepcopy(runtime.aar_bundle())
    support = [event for event in bundle["events"] if event["source"]["component"] == "exercise-support"]
    request_event, response = support
    if change == "staff_role":
        response["actor"]["role"] = "evaluator"
    elif change == "public_visibility":
        response["visibility"] = "participant"
    elif change == "foreign_source":
        response["source"]["component"] = "other-source"
    elif change == "missing_request":
        response["data"]["request_id"] = "unobserved"
    elif change == "duplicate_reply":
        duplicate = deepcopy(response)
        duplicate["sequence"] += 1
        duplicate["event_id"] = "adfe780a-5dd7-4b2c-8f91-c3e59976ab0b"
        bundle["events"].append(duplicate)
    elif change == "objective":
        request_event["objective_ids"] = ["LO5"]
    elif change == "reply_clock":
        request_event["data"]["elapsed_seconds"] = 10
    elif change == "dry_run":
        response["safety"]["dry_run"] = True
    else:
        response["data"]["response_key"] = ""
    bundle["content_sha256"] = _digest({key: value for key, value in bundle.items() if key != "content_sha256"})
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_preview_is_inert_and_explicit_demo_uses_real_workflow(monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview constructed a runtime")

    with monkeypatch.context() as patch:
        patch.setattr(support_demo, "PortalService", forbidden)
        assert support_demo.main([]) == 0
        assert json.loads(capsys.readouterr().out)["writes_performed"] is False
    result = support_demo.demonstrate()
    assert result["stale_run_rejected"] and result["new_run_request_count"] == 0
    assert result["reviewed_objectives"] == 0 and result["aar_status"] == "provisional"
    assert result["archived_support"][0]["response"]["kind"] == "clarification"
