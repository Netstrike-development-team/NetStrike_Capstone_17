"""Profile initialization, pinned reset, and confidence-bearing shared evidence."""

import json
from datetime import datetime, timezone

import pytest

from orchestrator.identity_slice import DEFAULT_PROFILE_PATH, DEFAULT_SCENARIO_PATH, IdentitySliceRun
from shared.profiles import ProfileInitializationError
from shared.events import EventValidator
from shared.actions import make_action_request
from shared.events import entity


def test_startup_preparation_binds_identity_helpdesk_and_confidence_evidence():
    events = []
    run = IdentitySliceRun(event_sink=events.append, run_id="profile-run", clock=lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    record = run.identity_state.snapshot()["identities"]["sarah"]
    assert record["employee_id"] == "emp_001"
    assert record["manager"] == "James Okafor"
    assert record["username"] == "sarah@simcorp.test"
    assert record["field_confidence"]["email_candidates"] == "inferred"
    assert run.identity_state.readiness_mismatches() == ()
    assert events == []  # invalid startup cannot leave an unvalidated initialization event
    run.controller.prepare()
    run.controller.prepare()
    startup = [e for e in events if e["event_type"] == "scenario.profiles.initialized"]
    assert len(startup) == 1
    assert startup[0]["visibility"] == "facilitator"
    assert startup[0]["data"]["catalog_sha256"] == run.profiles.fingerprint
    ticket = next(e for e in events if e["event_type"] == "helpdesk.identity_reset.completed")
    context = run.profiles.context()
    assert ticket["actor"]["id"] == context["helpdesk"]["identity_id"]
    assert ticket["target"]["id"] == context["identity"]["identity_id"]
    assert ticket["data"]["manager"] == context["manager"]["display_name"]
    assert ticket["data"]["field_confidence"]["email_candidates"] == "inferred"
    assert ticket["correlation_ids"] == [context["identity"]["profile_id"], context["helpdesk"]["profile_id"]]
    for event in events:
        EventValidator().validate(event)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))


def test_reset_pins_validated_profiles_even_if_source_file_changes(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_bytes(DEFAULT_PROFILE_PATH.read_bytes())
    run = IdentitySliceRun(event_sink=lambda _event: None, profile_path=path)
    baseline = run.identity_state.snapshot()
    fingerprint = run.profiles.fingerprint
    run.controller.start()
    run.identity_state.identities["sarah"]["enabled"] = False
    run.identity_state.identities["sarah"]["email_candidates"].clear()
    assert run.identity_state.readiness_mismatches() == ("identities",)
    path.write_text('{"unapproved":true}', encoding="utf-8")
    run.fail_safe_stop("reset test")
    run.reset(new_run_id="profile-reset")
    assert run.identity_state.snapshot() == baseline
    assert run.profiles.fingerprint == fingerprint
    assert run.identity_state.readiness_mismatches() == ()
    with pytest.raises(ProfileInitializationError):
        IdentitySliceRun(event_sink=lambda _event: None, profile_path=path)


def test_invalid_fixture_fails_before_any_runtime_evidence(tmp_path):
    path = tmp_path / "profiles.json"
    payload = json.loads(DEFAULT_PROFILE_PATH.read_text())
    payload["profiles"][0]["username"] = "real-person@external.com"
    path.write_text(json.dumps(payload), encoding="utf-8")
    events = []
    with pytest.raises(ProfileInitializationError):
        IdentitySliceRun(event_sink=events.append, profile_path=path)
    assert events == []


@pytest.mark.parametrize("change", ["missing", "seed", "identity", "helpdesk", "sso", "mfa", "identity_mapping"])
def test_invalid_scenario_binding_fails_initialization(tmp_path, change):
    definition = json.loads(DEFAULT_SCENARIO_PATH.read_text())
    experience = definition["participant_experience"]
    if change == "missing":
        experience.pop("profiles")
    elif change == "seed":
        experience["profiles"]["seed"] = "wrong-seed"
    elif change == "identity":
        experience["profiles"]["identity_employee_id"] = "emp_005"
    elif change == "helpdesk":
        experience["profiles"]["helpdesk_employee_id"] = "emp_006"
    elif change in {"sso", "mfa"}:
        experience[change] = None
    else:
        experience["sso"]["identity"] = None
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    with pytest.raises(ProfileInitializationError):
        IdentitySliceRun(event_sink=lambda _event: None, scenario_path=path)


def test_identity_reset_adapter_restores_seeded_metadata_not_legacy_baseline():
    run = IdentitySliceRun(event_sink=lambda _event: None, run_id="profile-adapter-reset")
    baseline = run.identity_state.snapshot()
    run.identity_state.identities["sarah"]["manager"] = "corrupted"
    run.identity_state.identities["sarah"]["enabled"] = False
    run.controller.fail_safe_stop("standalone reset-adapter test")
    request = make_action_request(
        exercise_id=run.definition.exercise_id, run_id=run.run_id,
        actor=entity("facilitator", "staff", role="facilitator"),
        action_id="exercise.identity.reset", target=entity("exercise_run", run.run_id),
        idempotency_key="seeded-identity-reset", dry_run=False,
    )
    result = run.identity_adapter.execute(request)
    assert result["successful"] is True
    assert run.identity_state.snapshot() == baseline
    assert run.identity_state.readiness_mismatches() == ()
