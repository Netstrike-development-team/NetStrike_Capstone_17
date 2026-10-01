"""Full-play impact/recovery safety and evidence integration."""

from datetime import datetime, timezone
import json
import sys

import pytest

from orchestrator.checkpoints import EvidenceReference, IdentityTriageSubmission
from orchestrator.controller import ControllerError, ItemStatus, RunState
from orchestrator.identity_slice import IdentitySliceRun
from orchestrator.impact import FULL_SCENARIO_PATH
from shared.actions import ActionContractError, ActionExecutionError
from shared.events import EventLedger, EventValidator, entity

FIXTURE = "FILE01-disposable-fixture"
NOW = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)


def build(tmp_path):
    root = tmp_path / "disposable"
    root.mkdir()
    events = []
    run = IdentitySliceRun(
        event_sink=events.append, run_id="full-test",
        scenario_path=FULL_SCENARIO_PATH, impact_root=root, clock=lambda: NOW,
    )
    run.controller.prepare()
    run.controller.start()
    return run, events


def to_impact(run):
    run.controller.advance_to(1500)
    run.submit_dp1(IdentityTriageSubmission(
        affected_identity="sarah", classification="account compromise",
        evidence=(EvidenceReference("HD-1042", "helpdesk"),
                  EvidenceReference("factor-red-01", "identity"),
                  EvidenceReference("sess-red-01", "identity")),
    ))
    run.controller.advance_to(3600)
    run.resolve_dp2()
    run.controller.advance_to(5700)
    run.cloud.resolve()
    run.controller.advance_to(6600)


def prevent(run, *, task_only=False):
    actions = [("endpoint.process.stop", "process", "impact-task-01")]
    if not task_only:
        actions.extend([
            ("endpoint.host.isolate", "host", "FIN-WS01"),
            ("ad.persistence.remove", "directory_account", "svc-print-sync"),
        ])
    for action_id, target_type, target_id in actions:
        result = run.submit_action(
            actor=entity("participant", "endpoint-learner", role="endpoint_responder"),
            action_id=action_id, target=entity(target_type, target_id),
            idempotency_key=action_id,
        )
        assert result["successful"]


def recover(run, action_id="recovery.fixture.restore", *, key=None, dry_run=False, role="cloud_responder"):
    return run.impact.recover(
        actor=entity("participant", "recovery-learner", role=role),
        action_id=action_id, fixture_id=FIXTURE, key=key or action_id, dry_run=dry_run,
    )


def brief(run):
    return {
        "confirmed_scope": "Synthetic identity, host and customer-export incident.",
        "confirmed_cloud_records": run.cloud.state.exposure["simcorp-customer-exports"]["confirmed_count"],
        "business_impact": "Disposable export service was interrupted; no real encryption.",
        "actions_taken": "Restored decoys from the supplied copy and validated hashes.",
        "remaining_risk": "Mock access does not establish external transfer.",
        "recommendations": ["Strengthen helpdesk verification.", "Review service-key access."],
        "evidence_ids": [run.impact.validation_event_id],
    }


def tree(fixture):
    return {
        str(path.relative_to(fixture.run_root)): path.read_bytes()
        for path in fixture.run_root.rglob("*") if path.is_file() and not path.is_symlink()
    }


def test_full_scenario_is_explicit_and_timed(tmp_path):
    with pytest.raises(ValueError, match="NETSTRIKE_IMPACT_ROOT"):
        IdentitySliceRun(event_sink=lambda _event: None, scenario_path=FULL_SCENARIO_PATH)
    run, _events = build(tmp_path)
    assert run.impact.prepared
    assert run.endpoint_state.processes["impact-task-01"]["active"]
    assert run.impact.fixture.inspect()["baseline_verified"]
    times = {item.item_id: item.trigger.seconds for item in run.definition.items}
    assert times["DP4"] == 6600 and times["END-01"] == 7800


def test_blocked_branch_preserves_available_originals_and_hash_proof(tmp_path):
    run, events = build(tmp_path)
    to_impact(run)
    prevent(run)
    result = run.impact.resolve()
    status = run.impact.fixture.inspect()
    assert result.passed
    assert status["available_originals"] == 5
    assert status["originals_unchanged"] and status["backup_intact"]
    assert status["marker_count"] == 5 and not status["note_present"]
    assert run.controller.items["ACT-08A"].status == ItemStatus.DELIVERED
    for event in events:
        EventValidator().validate(event)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


def test_realized_branch_only_moves_unchanged_decoys(tmp_path):
    run, _events = build(tmp_path)
    original = {name: (run.impact.fixture.live_dir / name).read_bytes()
                for name in run.impact.fixture.expected_manifest}
    to_impact(run)
    assert not run.impact.resolve().passed
    status = run.impact.fixture.inspect()
    assert status["available_originals"] == 0 and status["marker_count"] == 5
    assert status["note_present"] and status["originals_unchanged"]
    for name, content in original.items():
        assert (run.impact.fixture.staging_dir / name).read_bytes() == content
        assert (run.impact.fixture.backup_dir / name).read_bytes() == content
    assert status["encryption_performed"] is False


def test_partial_prevention_never_rearms_a_stopped_task(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    prevent(run, task_only=True)
    assert not run.impact.resolve().passed
    assert run.controller.items["ACT-08B"].status == ItemStatus.DELIVERED
    assert run.impact.fixture.inspect()["available_originals"] == 5
    assert run.impact.fixture.last_report["variant"] == "blocked"


def test_preview_is_default_and_cannot_count_as_recovery_or_health(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    before = tree(run.impact.fixture)
    result = run.impact.recover(
        actor=entity("participant", "recovery", role="cloud_responder"),
        action_id="recovery.fixture.restore", fixture_id=FIXTURE, key="default-preview",
    )
    assert result["status"] == "dry_run"
    assert tree(run.impact.fixture) == before
    assert run.impact.validation_event_id is None
    assert not run.impact.evaluate_recovery().passed


def test_restore_validate_brief_and_end_freeze_observations(tmp_path):
    run, events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    assert recover(run)["successful"]
    assert recover(run, "recovery.health.validate")["successful"]
    run.impact.submit_brief(brief(run))
    assert run.impact.evaluate_recovery().passed
    run.controller.advance_to(7800)
    assert run.controller.state == RunState.COMPLETED
    assert run.impact.final_review.passed
    final = next(e for e in events if e["event_type"] == "recovery.review.completed")
    assert final["visibility"] == "evaluator"
    assert final["data"]["passed"]
    assert final["data"]["report_quality_requires_evaluator"]
    assert run.impact.fixture.inspect()["baseline_verified"]
    assert not recover(run, key="after-end")["successful"]


def test_missing_brief_is_a_learner_miss_not_a_platform_fault(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    run.controller.advance_to(7800)
    assert run.controller.state == RunState.COMPLETED
    assert not run.impact.final_review.passed
    assert not run.impact.final_review.checks["communication_sections_present"]


def test_preview_validation_does_not_create_false_health_evidence(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    recover(run)
    assert recover(run, "recovery.health.validate", dry_run=True)["status"] == "dry_run"
    assert run.impact.validation_event_id is None


@pytest.mark.parametrize("role", ["soc_analyst", "endpoint_responder", "identity_responder"])
def test_recovery_role_denial_is_nonmutating(tmp_path, role):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    before = tree(run.impact.fixture)
    result = recover(run, role=role)
    assert result["error_code"] == "role_denied"
    assert tree(run.impact.fixture) == before


def test_wrong_target_and_extra_parameters_never_accept_filesystem_paths(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"never change me")
    result = run.impact.recover(
        actor=entity("participant", "recovery", role="cloud_responder"),
        action_id="recovery.fixture.restore", fixture_id=str(outside),
        key="outside-target", dry_run=False,
    )
    assert result["error_code"] == "target_denied"
    assert outside.read_bytes() == b"never change me"
    with pytest.raises(ActionContractError):
        run.submit_action(
            actor=entity("participant", "learner", role="cloud_responder"),
            action_id="impact.marker.apply", target=entity("fixture_set", FIXTURE),
            idempotency_key="forge-marker",
        )


def test_partial_apply_failure_rolls_back_then_stop_reset_succeeds(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    before = tree(run.impact.fixture)
    def fail(label):
        if label.startswith("marked:"):
            raise OSError("synthetic write fault")
    run.impact.fixture.fault_injector = fail
    run.impact.resolve()
    assert run.controller.items["ACT-08B"].status == ItemStatus.FAILED
    assert tree(run.impact.fixture) == before
    run.fail_safe_stop("fault drill")
    run.impact.fixture.fault_injector = None
    run.reset(new_run_id="after-partial-failure")
    assert run.impact.fixture.inspect()["baseline_verified"]


def test_stop_during_marker_application_cancels_and_restores_originals(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    prevent(run)
    before = tree(run.impact.fixture)
    marked = []
    def stop(label):
        if label.startswith("marked:"):
            marked.append(label)
            if len(marked) == 2:
                run.fail_safe_stop("injected partial execution stop")
    run.impact.fixture.fault_injector = stop
    run.impact.resolve()
    assert run.controller.state == RunState.STOPPED
    assert run.controller.items["ACT-08A"].status == ItemStatus.FAILED
    assert run.controller.items["ACT-08B"].status == ItemStatus.PENDING
    assert tree(run.impact.fixture) == before
    run.impact.fixture.fault_injector = None
    run.reset(new_run_id="after-forced-stop")
    assert run.impact.fixture.inspect()["baseline_verified"]


def test_partial_recovery_failure_restores_exact_impacted_state(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    before = tree(run.impact.fixture)
    def fail(label):
        if label.startswith("restored:"):
            raise OSError("synthetic restore failure")
    run.impact.fixture.fault_injector = fail
    assert recover(run)["error_code"] == "recovery_failed"
    assert tree(run.impact.fixture) == before
    assert run.impact.fixture.inspect()["originals_unchanged"]


def test_reset_restores_old_decoys_before_provisioning_a_new_run(tmp_path):
    run, events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    old = run.impact.fixture
    run.fail_safe_stop("reset drill")
    run.reset(new_run_id="next-full-run")
    assert old.inspect()["baseline_verified"]
    assert run.impact.fixture.inspect()["baseline_verified"]
    assert run.impact.audit == [] and run.impact.brief is None
    assert not run.impact.prepared and not run.impact.applied
    assert run.run_id == "next-full-run"
    assert any(e["event_type"] == "impact.baseline.restored" for e in events)


def test_corrupt_backup_blocks_reset_without_advancing_run(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    backup = run.impact.fixture.backup_dir / "billing-export.csv"
    backup.write_bytes(b"corrupt synthetic copy")
    run.fail_safe_stop("backup fault")
    before = tree(run.impact.fixture)
    with pytest.raises(ActionContractError, match="reset failed"):
        run.reset(new_run_id="not-admitted")
    assert run.run_id == "full-test" and run.controller.state == RunState.STOPPED
    assert tree(run.impact.fixture) == before
    assert not (run.impact.root / "not-admitted").exists()


@pytest.mark.parametrize("new_id", ["../escape", "/outside", "full-test"])
def test_unsafe_or_reused_reset_target_is_rejected_before_cleanup(tmp_path, new_id):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    run.fail_safe_stop("reset test")
    before = tree(run.impact.fixture)
    with pytest.raises(ActionContractError):
        run.reset(new_run_id=new_id)
    assert tree(run.impact.fixture) == before


def test_staff_rollback_is_current_run_and_one_use(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    assert run.impact.rollback(entity("facilitator", "staff", role="facilitator"))
    assert run.impact.fixture.inspect()["baseline_verified"]
    assert run.impact.validation_event_id is None
    with pytest.raises(ActionContractError):
        run.impact.rollback(entity("facilitator", "staff", role="facilitator"))


def test_outside_symlink_is_read_write_denied_and_stop_remains_usable(tmp_path):
    run, _events = build(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside immutable")
    path = run.impact.fixture.live_dir / "billing-export.csv"
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ActionExecutionError, match="unsafe"):
        run.impact.view()
    assert run.impact.staff_state()["health_error"] == "unsafe_or_unreadable_fixture"
    run.fail_safe_stop("unsafe fixture")
    with pytest.raises(ActionContractError):
        run.reset(new_run_id="unsafe-reset")
    assert outside.read_bytes() == b"outside immutable"


def test_root_with_unrelated_data_is_never_adopted(tmp_path):
    untouched = tmp_path / "personal.txt"
    untouched.write_bytes(b"keep")
    with pytest.raises(ValueError, match="empty"):
        IdentitySliceRun(
            event_sink=lambda _e: None, run_id="never-created",
            scenario_path=FULL_SCENARIO_PATH, impact_root=tmp_path,
        )
    assert untouched.read_bytes() == b"keep"
    assert not (tmp_path / "never-created").exists()


def test_early_branch_and_end_delivery_are_denied(tmp_path):
    run, _events = build(tmp_path)
    with pytest.raises(ControllerError, match="due"):
        run.impact.resolve()
    run.controller.deliver("ACT-08B")
    assert run.controller.items["ACT-08B"].status == ItemStatus.FAILED
    run.controller.deliver("END-01")
    assert run.controller.items["END-01"].status == ItemStatus.FAILED
    assert run.impact.fixture.inspect()["baseline_verified"]


def test_stale_recovery_reference_is_not_accepted_in_new_run(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    recover(run)
    recover(run, "recovery.health.validate")
    payload = brief(run)
    run.fail_safe_stop("new run")
    run.reset(new_run_id="new-reference-run")
    run.controller.prepare()
    run.controller.start()
    to_impact(run)
    run.impact.resolve()
    with pytest.raises(ActionContractError, match="current-run"):
        run.impact.submit_brief(payload)


@pytest.mark.parametrize("outcome,passed,available,variant", [
    ("blocked", True, 5, "blocked"),
    ("realized", False, 0, "realized"),
    ("partial", False, 5, "blocked"),
])
def test_full_play_demo_is_repeatable_without_real_encryption(tmp_path, outcome, passed, available, variant):
    from orchestrator.impact_demo import run_demo
    root = tmp_path / "demo-root"
    root.mkdir()
    summary, events = run_demo(outcome, root)
    assert summary["dp4_prevention_passed"] is passed
    assert summary["available_before_recovery"] == available
    assert summary["actual_marker_variant"] == variant
    assert summary["baseline_restored"] and summary["originals_unchanged"]
    assert summary["recovery_observations_passed"]
    assert summary["play_state"] == "completed"
    assert summary["encryption_performed"] is False
    assert summary["events_validated"] == len(events)


def test_cloud_evidence_fault_never_fabricates_a_notification_or_final_grade(tmp_path, monkeypatch):
    run, events = build(tmp_path)
    run.controller.advance_to(1500)
    run.submit_dp1(IdentityTriageSubmission(
        affected_identity="sarah", classification="account compromise",
        evidence=(EvidenceReference("HD-1042", "helpdesk"),
                  EvidenceReference("factor-red-01", "identity"),
                  EvidenceReference("sess-red-01", "identity")),
    ))
    run.controller.advance_to(3600)
    run.resolve_dp2()
    run.controller.advance_to(5700)
    emit = run.cloud._evidence
    def fail(action_id):
        if action_id == "cloud.bulk.attempt":
            raise RuntimeError("synthetic cloud evidence fault")
        emit(action_id)
    monkeypatch.setattr(run.cloud, "_evidence", fail)
    run.cloud.resolve()
    run.controller.advance_to(6600)
    assert run.controller.items["MSEL-08"].status == ItemStatus.FAILED
    assert not any(
        event["event_type"] == "scenario.item.delivered"
        and event["target"]["id"] == "MSEL-08" for event in events
    )
    run.impact.resolve()
    run.controller.advance_to(7800)
    assert run.controller.items["END-01"].status == ItemStatus.FAILED
    assert run.impact.final_review is None
    assert run.controller.state == RunState.RUNNING


def test_incorrect_scope_cannot_pass_recovery_observations(tmp_path):
    run, _events = build(tmp_path)
    to_impact(run)
    run.impact.resolve()
    recover(run)
    recover(run, "recovery.health.validate")
    report = brief(run)
    report["confirmed_cloud_records"] = 5
    run.impact.submit_brief(report)
    assert not run.impact.evaluate_recovery().checks["scope_count_supported"]


def test_cli_preview_performs_no_provisioning(tmp_path, monkeypatch, capsys):
    from orchestrator.impact_demo import main
    monkeypatch.setattr(sys, "argv", ["impact-demo", "--root", str(tmp_path)])
    main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] and not summary["writes_performed"]
    assert not list(tmp_path.iterdir())


def test_cli_export_uses_declared_virtual_clock(tmp_path, monkeypatch, capsys):
    from orchestrator.impact_demo import DEMO_TIME, main
    path = tmp_path / "new-demo.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "impact-demo", "--execute", "--outcome", "realized", "--events", str(path),
    ])
    main()
    summary = json.loads(capsys.readouterr().out)
    ledger = EventLedger(path, clock=lambda: DEMO_TIME)
    assert ledger.event_count == summary["events_validated"]
    assert summary["play_state"] == "completed"


def test_cli_never_overwrites_an_existing_export(tmp_path, monkeypatch):
    from orchestrator.impact_demo import main
    path = tmp_path / "existing.jsonl"
    path.write_bytes(b"existing evidence")
    monkeypatch.setattr(sys, "argv", ["impact-demo", "--execute", "--events", str(path)])
    with pytest.raises(SystemExit):
        main()
    assert path.read_bytes() == b"existing evidence"
