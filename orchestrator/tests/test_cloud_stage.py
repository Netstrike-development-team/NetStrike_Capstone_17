"""Exercise cloud branches from current state, not claimed attacker success."""

from datetime import datetime, timezone
import socket

import pytest

from orchestrator.cloud import CLOUD_SCENARIO_PATH
from orchestrator.controller import ControllerError, ItemStatus
from orchestrator.identity_slice import IdentitySliceRun
from shared.actions import ActionContractError
from shared.events import EventValidator, entity

NOW = datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)
PRINCIPAL = "svc-cloud-backup"
KEY = "svc-cloud-backup-key-01"
BUCKET = "simcorp-customer-exports"


def build():
    events = []
    run = IdentitySliceRun(
        event_sink=events.append, scenario_path=CLOUD_SCENARIO_PATH,
        run_id="cloud-test-run", clock=lambda: NOW,
    )
    run.controller.prepare()
    run.controller.start()
    return run, events


def action(run, action_id, target_type, target_id, *, role="cloud_responder", key=None, dry_run=False):
    return run.submit_action(
        actor=entity("participant", "cloud-learner", role=role),
        action_id=action_id, target=entity(target_type, target_id),
        idempotency_key=key or action_id, dry_run=dry_run,
    )


def assessment(run, **overrides):
    latest = [
        event for event in run.cloud.audit
        if event["event_type"] == "cloud.object.accessed"
    ][-1]
    payload = {
        "principal_id": PRINCIPAL,
        "confirmed_count": run.cloud.state.exposure[BUCKET]["confirmed_count"],
        "conclusion": "mock_access_only", "evidence_ids": [latest["event_id"]],
    }
    payload.update(overrides)
    run.cloud.submit_assessment(**payload)


def contain(run):
    assert action(run, "cloud.key.revoke", "cloud_key", KEY)["successful"]
    assert action(run, "cloud.policy.restore", "cloud_bucket", BUCKET)["successful"]


def test_combined_fixture_follows_approved_compressed_msel():
    run, _events = build()
    times = {item.item_id: item.trigger.seconds for item in run.definition.items}
    assert times["DP1"] == 1500
    assert times["DP2"] == 3600
    assert times["ACT-05"] == 3900
    assert times["ACT-06"] == 4500
    assert times["DP3"] == 5700
    assert not any(runtime.status == ItemStatus.FAILED for runtime in run.controller.items.values())


def test_scheduled_access_and_policy_change_generate_reviewable_objects_and_audit():
    run, events = build()
    run.controller.advance_to(4500)
    state = run.cloud.view()["state"]
    assert len(state["objects"]) == 25
    assert state["exposure"][BUCKET]["confirmed_count"] == 5
    assert state["buckets"][BUCKET]["bulk_access_allowed"]
    assert {event["event_type"] for event in run.cloud.audit} >= {
        "cloud.authentication.succeeded", "cloud.bucket.enumerated",
        "cloud.policy.changed", "cloud.object.accessed",
    }
    for event in events:
        EventValidator().validate(event)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["run_id"] == run.run_id for event in run.cloud.audit)
    assert all(event["data"]["external_transfer_observed"] is False for event in run.cloud.audit)


def test_correct_containment_and_assessment_select_limited_branch():
    run, events = build()
    run.controller.advance_to(4500)
    assessment(run)
    contain(run)
    run.controller.advance_to(5700)
    assert run.cloud.resolve().passed
    assert run.controller.items["ACT-07A"].status == ItemStatus.DELIVERED
    assert run.controller.items["ACT-07B"].status == ItemStatus.SKIPPED
    assert run.cloud.state.exposure[BUCKET]["confirmed_count"] == 5
    assert any(event["event_type"] == "cloud.bulk_access.blocked" for event in events)
    assert not any(event["event_type"] == "cloud.extortion.claimed" for event in events)


def test_uncontained_state_selects_full_exposure_but_never_external_transfer():
    run, events = build()
    run.controller.advance_to(5700)
    assessment(run)
    assert not run.cloud.resolve().passed
    assert run.cloud.state.exposure[BUCKET]["confirmed_count"] == 25
    assert run.controller.items["ACT-07B"].status == ItemStatus.DELIVERED
    assert run.controller.items["ACT-07A"].status == ItemStatus.SKIPPED
    claim = next(event for event in events if event["event_type"] == "cloud.extortion.claimed")
    assert claim["data"]["claim_only"] is True
    assert claim["data"]["external_transfer_observed"] is False


@pytest.mark.parametrize("remediation", ["cloud.key.revoke", "cloud.principal.disable", "cloud.policy.restore"])
def test_missed_checkpoint_never_bypasses_actual_partial_containment(remediation):
    run, events = build()
    run.controller.advance_to(4500)
    target_type, target_id = {
        "cloud.key.revoke": ("cloud_key", KEY),
        "cloud.principal.disable": ("cloud_principal", PRINCIPAL),
        "cloud.policy.restore": ("cloud_bucket", BUCKET),
    }[remediation]
    assert action(run, remediation, target_type, target_id)["successful"]
    run.controller.advance_to(5700)
    assert not run.cloud.resolve().passed  # no complete evidenced assessment
    assert run.cloud.state.exposure[BUCKET]["confirmed_count"] == 5
    assert any(event["event_type"] == "cloud.bulk_access.blocked" for event in events)
    assert not any(event["event_type"] == "cloud.extortion.claimed" for event in events)


def test_preemptive_key_revoke_yields_zero_realistically_not_manufactured_five():
    run, _events = build()
    action(run, "cloud.key.revoke", "cloud_key", KEY)
    run.controller.advance_to(4500)
    assessment(run)
    run.controller.advance_to(5700)
    assert run.cloud.resolve().passed
    assert run.cloud.state.exposure[BUCKET]["confirmed_count"] == 0


@pytest.mark.parametrize("overrides,failed_check", [
    ({"principal_id": "different-principal"}, "principal_identified"),
    ({"confirmed_count": 25}, "exposure_count_supported"),
    ({"conclusion": "external_transfer_proven"}, "transfer_not_overclaimed"),
    ({"conclusion": "unknown"}, "transfer_not_overclaimed"),
])
def test_unsupported_claims_fail_evaluation_without_changing_cloud_controls(overrides, failed_check):
    run, _events = build()
    run.controller.advance_to(4500)
    contain(run)
    assessment(run, **overrides)
    assert run.cloud.evaluate().checks[failed_check] is False
    assert run.cloud.state.keys[KEY]["active"] is False


@pytest.mark.parametrize("references", [["invented-id"], ["old-run-id"], []])
def test_evidence_must_be_current_run_audit(references):
    run, _events = build()
    run.controller.advance_to(4500)
    with pytest.raises(ActionContractError):
        assessment(run, evidence_ids=references)
    assert run.cloud.assessment is None


def test_authentication_event_alone_does_not_support_exposure_estimate():
    run, _events = build()
    run.controller.advance_to(4500)
    contain(run)
    reference = run.cloud.audit[0]["event_id"]
    assessment(run, evidence_ids=[reference])
    assert not run.cloud.evaluate().checks["exposure_evidence_cited"]


def test_preservation_is_immutable_and_reset_cleans_all_cloud_state():
    run, _events = build()
    run.controller.advance_to(4500)
    action(run, "cloud.evidence.preserve", "cloud_bucket", BUCKET)
    original = run.cloud.state.snapshot()["preserved_evidence"]
    contain(run)
    action(run, "cloud.evidence.preserve", "cloud_bucket", BUCKET, key="preserve-again")
    assert run.cloud.state.preserved_evidence == original
    assert original["state"]["keys"][KEY]["active"] is True
    assert original["audit"] == run.cloud.audit
    run.fail_safe_stop("reset test")
    run.reset(new_run_id="clean-cloud-run")
    assert run.cloud.state.readiness_mismatches() == ()
    assert run.cloud.audit == []
    assert run.cloud.assessment is None
    assert not run.cloud.access_staged


def test_read_only_views_are_defensive_copies():
    run, _events = build()
    run.controller.advance_to(4500)
    view = run.cloud.view()
    view["state"]["keys"][KEY]["active"] = False
    view["audit"].clear()
    assert run.cloud.state.keys[KEY]["active"]
    assert run.cloud.audit


@pytest.mark.parametrize("role,target_type,target_id,error", [
    ("endpoint_responder", "cloud_key", KEY, "role_denied"),
    ("cloud_responder", "cloud_key", "outside-key", "target_denied"),
    ("cloud_responder", "cloud_bucket", BUCKET, "target_denied"),
])
def test_role_and_target_denial_is_nonmutating(role, target_type, target_id, error):
    run, _events = build()
    before = run.cloud.state.snapshot()
    result = action(run, "cloud.key.revoke", target_type, target_id, role=role)
    assert result["error_code"] == error
    assert run.cloud.state.snapshot() == before


def test_dry_run_and_idempotent_retry_do_not_duplicate_mutation():
    run, _events = build()
    before = run.cloud.state.snapshot()
    result = action(run, "cloud.key.revoke", "cloud_key", KEY, dry_run=True, key="preview")
    assert result["status"] == "dry_run"
    assert run.cloud.state.snapshot() == before
    first = action(run, "cloud.key.revoke", "cloud_key", KEY, key="once")
    second = action(run, "cloud.key.revoke", "cloud_key", KEY, key="once")
    assert first["cached"] is False
    assert second["cached"] is True
    assert first["request_id"] == second["request_id"]


def test_pause_and_stop_block_cloud_mutations():
    run, _events = build()
    run.controller.pause()
    result = action(run, "cloud.key.revoke", "cloud_key", KEY, key="paused")
    assert not result["successful"]
    run.fail_safe_stop("platform issue")
    result = action(run, "cloud.key.revoke", "cloud_key", KEY, key="stopped")
    assert result["error_code"] == "run_stopped"
    assert run.cloud.state.keys[KEY]["active"]


def test_early_checkpoint_and_manual_branch_delivery_fail_closed():
    run, _events = build()
    with pytest.raises(ControllerError, match="due"):
        run.cloud.resolve()
    run.controller.advance_to(4500)
    before = run.cloud.state.snapshot()
    run.controller.deliver("ACT-07B")
    assert run.controller.items["ACT-07B"].status == ItemStatus.FAILED
    assert run.cloud.state.snapshot() == before
    run.controller.advance_to(5700)
    with pytest.raises(ControllerError, match="branch unavailable"):
        run.cloud.resolve()


def test_skipped_cloud_source_is_platform_failure_not_participant_miss():
    run, _events = build()
    run.controller.skip("ACT-05", "missing telemetry")
    run.controller.advance_to(5700)
    with pytest.raises(ControllerError, match="incomplete"):
        run.cloud.resolve()
    assert "DP3" not in run.controller.checkpoint_results


def test_evidence_emission_fault_blocks_grading_even_if_state_transition_ran(monkeypatch):
    run, _events = build()
    emit = run.cloud._evidence

    def faulty(action_id):
        if action_id == "cloud.policy.expand":
            raise RuntimeError("synthetic telemetry fault")
        emit(action_id)

    monkeypatch.setattr(run.cloud, "_evidence", faulty)
    run.controller.advance_to(5700)
    assert run.cloud.policy_attempted
    assert run.controller.items["ACT-06"].status == ItemStatus.FAILED
    with pytest.raises(ControllerError, match="incomplete"):
        run.cloud.resolve()
    assert "DP3" not in run.controller.checkpoint_results


def test_cloud_stays_local_even_with_socket_creation_disabled(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("cloud stage attempted network access")
    monkeypatch.setattr(socket, "socket", forbidden)
    run, _events = build()
    run.controller.advance_to(5700)
    run.cloud.resolve()
    assert run.cloud.state.exposure[BUCKET]["confirmed_count"] == 25


def test_duplicate_step_is_idempotent_and_correlation_mismatch_rejected():
    run, _events = build()
    run.controller.advance_to(3900)
    item = next(item for item in run.definition.items if item.item_id == "ACT-05")
    before = run.cloud.state.snapshot()
    audit_count = len(run.cloud.audit)
    assert run.cloud.handle(item, run.run_id).success
    assert run.cloud.state.snapshot() == before
    assert len(run.cloud.audit) == audit_count
    assert not run.cloud.handle(item, "other-run").success


def test_old_identity_demo_retains_its_boundary():
    run = IdentitySliceRun(event_sink=lambda _event: None)
    assert not run.cloud_enabled
    run.controller.start()
    with pytest.raises(ActionContractError, match="not available"):
        action(run, "cloud.key.revoke", "cloud_key", KEY)


@pytest.mark.parametrize("outcome,passed,count,blocked", [
    ("contained", True, 5, True), ("full", False, 25, False),
    ("partial", False, 5, True),
])
def test_developer_demo_is_repeatable_and_validates_events(outcome, passed, count, blocked):
    from orchestrator.cloud_demo import run_demo
    summary, events = run_demo(outcome)
    assert summary["checkpoint_passed"] is passed
    assert summary["confirmed_records"] == count
    assert summary["bulk_blocked"] is blocked
    assert summary["events_validated"] == len(events)


def test_logical_cloud_outcomes_match_jump_and_one_second_clock():
    jumping, _events = build()
    stepping, _other_events = build()
    jumping.controller.advance_to(4500)
    for second in range(4501):
        stepping.controller.advance_to(second)
    assert jumping.cloud.state.snapshot() == stepping.cloud.state.snapshot()
    assert [(e["event_type"], e["data"]) for e in jumping.cloud.audit] == [
        (e["event_type"], e["data"]) for e in stepping.cloud.audit
    ]
