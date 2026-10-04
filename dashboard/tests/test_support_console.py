"""Served offline support forms and coherent role/lifecycle metadata."""

from html.parser import HTMLParser
import pytest

from dashboard.tests.test_support import (
    portal, runtime, start, request, reply, headers,  # pylint: disable=unused-import
)


class Controls(HTMLParser):
    """Record static form IDs, field types and dependency URLs."""

    def __init__(self):
        super().__init__()
        self.ids = []
        self.fields = []
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag in {"input", "select", "textarea"}:
            self.fields.append(values)
        for field in ("src", "href"):
            if field in values:
                self.urls.append(values[field])


def test_three_pages_have_local_support_controls_and_unique_ids(portal):
    client, _service = portal
    for page in ("participant", "facilitator", "evaluator"):
        response = client.get("/" + page)
        assert response.status_code == 200
        parsed = Controls()
        parsed.feed(response.text)
        assert len(parsed.ids) == len(set(parsed.ids))
        assert {"support-summary", "support-refresh", "support-threads"} <= set(parsed.ids)
        assert all(not url.startswith(("http:", "https:", "//")) for url in parsed.urls)
        script = client.get(f"/static/{page}.js").text
        assert 'import {mountSupport} from "/static/support.js"' in script
        if page == "evaluator":
            assert "support-form" not in parsed.ids
            assert "observer: true" in script
        else:
            assert {"support-form", "support-send"} <= set(parsed.ids)
            prose = next(field for field in parsed.fields if field.get("name") == "message")
            assert prose["maxlength"] == "1024" and "required" in prose and "disabled" in prose
        if page == "facilitator":
            scope = [field["value"] for field in parsed.fields if field.get("name") == "objective_ids"]
            assert scope == ["LO1", "LO2", "LO3", "LO4", "LO5"]


def test_served_support_asset_is_plain_text_and_not_persistent(portal):
    client, _service = portal
    response = client.get("/static/support.js")
    assert response.status_code == 200
    assert "text/javascript" in response.headers["content-type"]
    for unsafe in ("innerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "eval("):
        assert unsafe not in response.text
    assert 'import {api, idempotency, token} from "./common.js"' in response.text
    assert 'cache: "no-store"' in response.text


def test_support_snapshot_reports_authenticated_role_and_current_state(portal):
    client, service = portal
    for role, route in (("soc_analyst", "participant"), ("facilitator", "facilitator"),
                        ("technical_operator", "facilitator"), ("evaluator", "facilitator")):
        response = client.get(f"/api/{route}/support", headers=headers(role))
        assert response.status_code == 200
        assert response.json()["principal_role"] == role
        assert response.json()["run_state"] == service.run.controller.state.value
        assert response.headers["cache-control"] == "no-store"
    start(service)
    question = request(service)
    reply(service, question)
    assert client.post("/api/facilitator/pause", headers=headers()).status_code == 200
    view = client.get("/api/facilitator/support", headers=headers()).json()
    assert view["run_state"] == "paused" and len(view["requests"]) == 1


@pytest.mark.parametrize("kind", ["question", "reply"])
def test_lost_support_ack_is_503_and_exact_api_retry_confirms_original(portal, monkeypatch, kind):
    client, service = portal
    start(service)
    path = "/api/participant/support"
    principal_headers = headers("soc_analyst")
    body = {"run_id": service.run.run_id, "idempotency_key": "ui-question-1",
            "objective_id": "LO2", "message": "How should I cite this evidence?"}
    event_type = "exercise.support.requested"
    if kind == "reply":
        receipt = client.post(path, headers=principal_headers, json=body).json()
        path = "/api/facilitator/support/replies"
        principal_headers = headers()
        body = {"run_id": service.run.run_id, "request_id": receipt["request_id"],
                "idempotency_key": "ui-reply-1", "kind": "clarification",
                "objective_ids": ["LO2"], "message": "A human-authored explanation."}
        event_type = "exercise.support.responded"
    append = service.store.append_event

    def lose_ack(event):
        append(event)
        if event["event_type"] == event_type:
            raise OSError("private failure detail must not be returned")

    monkeypatch.setattr(service.store, "append_event", lose_ack)
    failed = client.post(path, headers=principal_headers, json=body)
    assert failed.status_code == 503
    assert "private failure detail" not in failed.text
    assert service.run.controller.state.value == "stopped"
    monkeypatch.setattr(service.store, "append_event", append)
    retry = client.post(path, headers=principal_headers, json=body)
    assert retry.status_code == 200 and retry.json()["replayed"] is True
    stored = service.store.events(service.run.definition.exercise_id, service.run.run_id)
    assert sum(event["event_type"] == event_type for event in stored) == 1
