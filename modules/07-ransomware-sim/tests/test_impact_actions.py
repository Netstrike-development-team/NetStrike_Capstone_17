from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MODULE))

from impact_actions import (
    FIXTURE_CONTENTS,
    FIXTURE_ID,
    MARKER_SUFFIX,
    NOTE_NAME,
    ImpactFixture,
    build_impact_adapter,
)
from shared.actions import ActionExecutionError, make_action_request
from shared.events import EventValidator, entity

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)
EXERCISE_ID = "silent-spider"
RUN_ID = "run-impact-001"


def file_tree(fixture):
    return {
        str(path.relative_to(fixture.run_root)): path.read_bytes()
        for path in fixture.run_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def build_system(tmp_path, *, run_state="running", fault_injector=None):
    fixture = ImpactFixture.provision(tmp_path, RUN_ID, fault_injector=fault_injector)
    current = {"state": run_state}
    events = []
    adapter = build_impact_adapter(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        fixture=fixture,
        run_state=lambda _exercise, _run: current["state"],
        event_sink=events.append,
    )
    adapter.clock = lambda: NOW
    adapter.events.clock = lambda: NOW
    return fixture, adapter, events, current


def action_request(
    action_id,
    target_type,
    target_id,
    key,
    *,
    role,
    parameters=None,
    dry_run=False,
):
    return make_action_request(
        exercise_id=EXERCISE_ID,
        run_id=RUN_ID,
        actor=entity("participant", "learner-01", role=role),
        action_id=action_id,
        target=entity(target_type, target_id),
        idempotency_key=key,
        parameters=parameters or {},
        dry_run=dry_run,
        timeout_seconds=10,
        clock=lambda: NOW,
    )


def impact_request(key, variant="blocked", *, dry_run=False, role="scenario_engine"):
    return action_request(
        "impact.marker.apply",
        "fixture_set",
        FIXTURE_ID,
        key,
        role=role,
        parameters={"variant": variant},
        dry_run=dry_run,
    )


def recovery_request(key, *, role="cloud_responder"):
    return action_request(
        "recovery.fixture.restore",
        "fixture_set",
        FIXTURE_ID,
        key,
        role=role,
    )


def test_provision_creates_hash_verified_run_specific_fixture(tmp_path):
    fixture = ImpactFixture.provision(tmp_path, RUN_ID)

    assert fixture.run_root.parent == tmp_path.resolve()
    assert len(fixture.expected_manifest) == 5
    assert fixture.health_mismatches() == ()
    assert {path.name for path in fixture.live_dir.iterdir()} == set(FIXTURE_CONTENTS)
    assert {path.name for path in fixture.backup_dir.iterdir()} == set(FIXTURE_CONTENTS)


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", "", " space"])
def test_provision_rejects_unsafe_run_ids(tmp_path, run_id):
    with pytest.raises(ValueError, match="run_id"):
        ImpactFixture.provision(tmp_path, run_id)


def test_provision_refuses_to_overwrite_existing_run(tmp_path):
    ImpactFixture.provision(tmp_path, RUN_ID)

    with pytest.raises(ValueError, match="already exists"):
        ImpactFixture.provision(tmp_path, RUN_ID)


def test_blocked_variant_creates_five_markers_without_changing_originals(tmp_path):
    fixture, adapter, events, _current = build_system(tmp_path)
    original_tree = file_tree(fixture)

    result = adapter.execute(impact_request("blocked-impact"))

    assert result["status"] == "executed"
    assert fixture.health_mismatches() == ("live_manifest",)
    assert len(list(fixture.live_dir.glob(f"*{MARKER_SUFFIX}"))) == 5
    assert not (fixture.live_dir / NOTE_NAME).exists()
    assert not list(fixture.staging_dir.iterdir())
    for name, content in FIXTURE_CONTENTS.items():
        assert (fixture.live_dir / name).read_bytes() == content
        assert original_tree[f"live/{name}"] == content
    for event in events:
        EventValidator().validate(event)
    assert {event["phase"] for event in events if event["phase"] != "control"} == {
        "impact_recovery"
    }
    completion = events[-1]
    report = completion["data"]["metadata"]["manifest_report"]
    assert report["variant"] == "blocked"
    assert report["before"]["live"] == fixture.expected_manifest


def test_realized_variant_stages_originals_and_creates_safe_artifacts(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)

    result = adapter.execute(impact_request("realized-impact", "realized"))

    assert result["successful"] is True
    assert not any((fixture.live_dir / name).exists() for name in FIXTURE_CONTENTS)
    assert len(list(fixture.live_dir.glob(f"*{MARKER_SUFFIX}"))) == 5
    note = (fixture.live_dir / NOTE_NAME).read_text(encoding="utf-8")
    assert "NO ENCRYPTION" not in note
    assert "No encryption occurred" in note
    for name, content in FIXTURE_CONTENTS.items():
        assert (fixture.staging_dir / name).read_bytes() == content
    assert fixture.last_report["variant"] == "realized"
    assert fixture.last_report["before"]["live"] == fixture.expected_manifest
    assert fixture.last_report["after"]["staging"] == fixture.expected_manifest


def test_recovery_restores_known_good_files_and_removes_artifacts(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-recovery", "realized"))

    result = adapter.execute(recovery_request("restore-fixture"))

    assert result["successful"] is True
    assert fixture.health_mismatches() == ()
    assert not list(fixture.staging_dir.iterdir())
    assert not list(fixture.live_dir.glob(f"*{MARKER_SUFFIX}"))
    assert not (fixture.live_dir / NOTE_NAME).exists()


def test_impact_action_rollback_restores_exact_baseline(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    before = file_tree(fixture)
    request = impact_request("rollback-impact", "realized")
    adapter.execute(request)

    changes = adapter.rollback(
        request["request_id"], entity("facilitator", "fac-01", role="facilitator")
    )

    assert changes == ("restored pre-action disposable fixture",)
    assert file_tree(fixture) == before
    assert fixture.health_mismatches() == ()
    with pytest.raises(ActionExecutionError, match="already-used rollback token"):
        adapter.rollback(
            request["request_id"],
            entity("facilitator", "fac-01", role="facilitator"),
        )


def test_recovery_rollback_restores_impacted_state(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-for-recovery-rollback", "realized"))
    impacted = file_tree(fixture)
    request = recovery_request("recovery-to-rollback")
    adapter.execute(request)

    adapter.rollback(
        request["request_id"], entity("facilitator", "fac-01", role="facilitator")
    )

    assert file_tree(fixture) == impacted


def test_idempotent_replay_does_not_repeat_file_operations(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    request = impact_request("apply-once")

    first = adapter.execute(request)
    first_tree = file_tree(fixture)
    replay = adapter.execute(request)

    assert first["cached"] is False
    assert replay["cached"] is True
    assert file_tree(fixture) == first_tree
    assert len(fixture._rollbacks) == 1  # pylint: disable=protected-access


def test_new_request_against_dirty_fixture_fails_closed(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("first-impact"))
    before = file_tree(fixture)

    result = adapter.execute(impact_request("second-impact"))

    assert result["status"] == "failed"
    assert result["error_code"] == "fixture_not_ready"
    assert file_tree(fixture) == before


def test_invalid_variant_is_denied_without_file_changes(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    before = file_tree(fixture)

    result = adapter.execute(impact_request("invalid-variant", "encrypted"))

    assert result["status"] == "denied"
    assert result["error_code"] == "invalid_parameters"
    assert file_tree(fixture) == before


def test_wrong_target_and_role_are_denied_without_file_changes(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    before = file_tree(fixture)

    wrong_target = action_request(
        "impact.marker.apply",
        "fixture_set",
        "external-files",
        "wrong-target",
        role="scenario_engine",
        parameters={"variant": "blocked"},
    )
    target_result = adapter.execute(wrong_target)
    role_result = adapter.execute(
        impact_request("wrong-role", role="endpoint_responder")
    )

    assert target_result["error_code"] == "target_denied"
    assert role_result["error_code"] == "role_denied"
    assert file_tree(fixture) == before


def test_dry_run_does_not_write_files(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    before = file_tree(fixture)

    result = adapter.execute(impact_request("dry-run-impact", dry_run=True))

    assert result["status"] == "dry_run"
    assert file_tree(fixture) == before


def test_partial_impact_failure_rolls_back_every_file(tmp_path):
    calls = []

    def fail_on_second_marker(label):
        calls.append(label)
        if len([item for item in calls if item.startswith("marked:")]) == 2:
            raise OSError("injected write failure")

    fixture, adapter, _events, _current = build_system(
        tmp_path, fault_injector=fail_on_second_marker
    )
    before = file_tree(fixture)

    result = adapter.execute(impact_request("partial-impact", "realized"))

    assert result["status"] == "failed"
    assert result["error_code"] == "impact_apply_failed"
    assert file_tree(fixture) == before
    assert fixture.health_mismatches() == ()


def test_partial_recovery_failure_restores_impacted_state(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-failed-recovery", "realized"))
    impacted = file_tree(fixture)

    def fail_on_restore(label):
        if label.startswith("restored:"):
            raise OSError("injected restore failure")

    fixture.fault_injector = fail_on_restore
    result = adapter.execute(recovery_request("partial-recovery"))

    assert result["status"] == "failed"
    assert result["error_code"] == "recovery_failed"
    assert file_tree(fixture) == impacted


def test_symlink_is_rejected_without_touching_external_file(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    name = next(iter(FIXTURE_CONTENTS))
    external = tmp_path / "outside.txt"
    external.write_text("outside remains unchanged", encoding="utf-8")
    (fixture.live_dir / name).unlink()
    (fixture.live_dir / name).symlink_to(external)

    result = adapter.execute(impact_request("reject-symlink"))

    assert result["status"] == "failed"
    assert result["error_code"] == "unsafe_fixture"
    assert external.read_text(encoding="utf-8") == "outside remains unchanged"


def test_tampered_backup_prevents_recovery(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-backup-check", "realized"))
    impacted = file_tree(fixture)
    name = next(iter(FIXTURE_CONTENTS))
    (fixture.backup_dir / name).write_text("tampered", encoding="utf-8")

    result = adapter.execute(recovery_request("reject-tampered-backup"))

    assert result["status"] == "failed"
    assert result["error_code"] == "backup_mismatch"
    for relative, content in impacted.items():
        if not relative.startswith("known-good/"):
            assert (fixture.run_root / relative).read_bytes() == content


def test_health_action_reports_impacted_fixture(tmp_path):
    _fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-health-check"))

    result = adapter.execute(
        action_request(
            "recovery.health.validate",
            "fixture_set",
            FIXTURE_ID,
            "validate-dirty-fixture",
            role="cloud_responder",
        )
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "fixture_unhealthy"
    assert "live_manifest" in result["message"]


def test_reset_is_denied_while_run_is_active(tmp_path):
    fixture, adapter, _events, _current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-denied-reset"))
    before = file_tree(fixture)

    result = adapter.execute(
        action_request(
            "exercise.impact.reset",
            "exercise_run",
            RUN_ID,
            "reset-running",
            role="technical_operator",
        )
    )

    assert result["error_code"] == "invalid_run_state"
    assert file_tree(fixture) == before


def test_stopped_run_can_reset_and_validate_readiness(tmp_path):
    fixture, adapter, events, current = build_system(tmp_path)
    adapter.execute(impact_request("impact-before-reset", "realized"))
    current["state"] = "stopped"

    reset = adapter.execute(
        action_request(
            "exercise.impact.reset",
            "exercise_run",
            RUN_ID,
            "reset-stopped",
            role="technical_operator",
        )
    )
    current["state"] = "ready"
    readiness = adapter.execute(
        action_request(
            "exercise.impact.readiness.validate",
            "exercise_run",
            RUN_ID,
            "validate-ready",
            role="technical_operator",
        )
    )

    assert reset["successful"] is True
    assert readiness["successful"] is True
    assert fixture.health_mismatches() == ()
    for event in events:
        EventValidator().validate(event)
