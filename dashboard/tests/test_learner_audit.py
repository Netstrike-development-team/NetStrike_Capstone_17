"""Strict fact-only projection; source visibility alone never authorizes a row."""

import json
from copy import deepcopy

import pytest

from dashboard.learner_audit import RULES, project
from shared.events import EventBuilder, EventContext, entity


def audit(**changes):
    event = EventBuilder(EventContext("operation-silent-spider", "learner-test", "module", "helpdesk-simulator", "1.0.0")).build(
        event_type="helpdesk.identity_reset.completed", phase="identity",
        actor=entity("helpdesk_agent", "tyler"), action="helpdesk.identity_reset",
        target=entity("identity", "sarah"), outcome_status="success", visibility="participant",
        message="PRIVATE FREE TEXT / DP1 solution / score 100", dry_run=True,
        data={"ticket_id": "HD-1042", "callback_verified": False,
              "caller_claim": "PRIVATE CLAIM", "nested": {"answer": "PRIVATE ANSWER"}},
    )
    event.update(changes)
    return event


def test_explicit_audit_fields_not_messages_answers_or_arbitrary_data():
    event = audit()
    before = deepcopy(event)
    result = project(event)
    assert event == before
    assert result["service"] == "simcorp-helpdesk"
    assert result["event_type"] == "identity.reset.completed"
    assert result["facts"] == {"ticket_id": "HD-1042", "callback_verified": False}
    assert result["event_id"] == event["event_id"] and result["run_id"] == event["run_id"]
    assert result["actor_id"] == "tyler" and result["target_id"] == "sarah"
    assert result["simulated_service"] is True
    serialized = json.dumps(result)
    for forbidden in ("PRIVATE", "DP1", "solution", "score", "checkpoint", "visibility", "phase", "dry_run", "sequence"):
        assert forbidden not in serialized
    result["facts"]["ticket_id"] = "changed"
    assert event == before


@pytest.mark.parametrize("visibility", ["facilitator", "evaluator", "internal"])
def test_even_known_audits_are_private_without_public_source_visibility(visibility):
    assert project(audit(visibility=visibility)) is None


@pytest.mark.parametrize("event_type", ["scenario.item.delivered", "scenario.checkpoint.resolved",
    "objective.evaluated", "exercise.support.requested", "exercise.support.replied",
    "exercise.submission.received", "action.execution.completed", "recovery.health.verified",
    "impact.fixture.prepared", "directory.persistence.attempted", "cloud.extortion.claimed",
    "helpdesk.identity_reset.completed.extra"])
def test_unknown_controller_grading_help_submission_and_setup_events_never_project(event_type):
    assert project(audit(event_type=event_type)) is None


@pytest.mark.parametrize("kind,component", [("controller", "helpdesk-simulator"),
    ("module", "scenario-controller"), ("action_adapter", "helpdesk-simulator"),
    ("module", "unreviewed-helpdesk")])
def test_public_flag_and_known_event_name_do_not_bypass_producer_allowlist(kind, component):
    event = audit()
    event["source"].update(kind=kind, component=component)
    assert project(event) is None


@pytest.mark.parametrize("value", ["private prose with spaces", ["secret"], {"answer": "hidden"}, 17, "x" * 129])
def test_bad_selected_fact_blocks_instead_of_coercing_or_leaking(value):
    event = audit()
    event["data"]["ticket_id"] = value
    with pytest.raises(ValueError):
        project(event)


def test_boolean_and_number_facts_do_not_silently_coerce():
    event = audit()
    event["data"]["callback_verified"] = "false"
    with pytest.raises(ValueError):
        project(event)


def test_unredacted_source_fields_block_even_if_not_selected():
    event = audit()
    event["data"]["password"] = "synthetic-secret-that-must-not-export"
    with pytest.raises(ValueError, match="unredacted"):
        project(event)


@pytest.mark.parametrize("value", [None, [], "private", 17])
def test_nonobject_source_fails_without_attribute_errors(value):
    with pytest.raises(ValueError, match="object"):
        project(value)


def test_rule_contract_has_no_solution_or_controller_events():
    assert len(RULES) >= 20
    for name, (_producer, service, operation, fields) in RULES.items():
        assert not name.startswith(("scenario.", "objective.", "action.", "exercise."))
        assert service.startswith("simcorp-")
        assert not any(word in operation for word in ("fake", "malicious", "checkpoint", "grade", "extortion"))
        assert not fields & {"reason", "message", "approved_policy_hash", "expected_manifest", "msel_id", "contact_candidates", "field_confidence"}
