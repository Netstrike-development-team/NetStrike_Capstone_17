"""Native file copies must be observed, never repaired or trusted as learner claims."""

import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.auth import PortalPrincipal, TokenAuthenticator
from dashboard.service import PortalService
from dashboard.store import PortalStore
from dashboard.tests.test_recovery_api import (
    STAFF, SOC, RECOVERY, FIXTURE, action, advance, headers, payload, stage,
)
from orchestrator.impact import FULL_SCENARIO_PATH
from shared.events import EventValidator

MODULE = importlib.import_module("modules.07-ransomware-sim.impact_actions")


@pytest.fixture
def native(tmp_path):
    root = tmp_path / "fixtures"
    root.mkdir()
    store = PortalStore()
    service = PortalService(store, run_id="native-test", scenario_path=FULL_SCENARIO_PATH,
                            impact_root=root, recovery_mode="native_files")
    auth = TokenAuthenticator({
        STAFF: PortalPrincipal("facilitator", "facilitator"),
        RECOVERY: PortalPrincipal("recovery-learner", "cloud_responder"),
        SOC: PortalPrincipal("analyst", "soc_analyst"),
    })
    with TestClient(create_app(service, auth, sso_allowed_origins={"http://testserver"})) as client:
        stage(client)
        yield client, service
    store.close()


def files(fixture):
    return {str(p.relative_to(fixture.run_root)): p.read_bytes()
            for p in fixture.run_root.rglob("*") if p.is_file() and not p.is_symlink()}


def native_copy(fixture):
    """Ordinary OS copy in a separate process; never call the restore adapter."""
    for name in fixture.expected_manifest:
        subprocess.run(["/bin/cp", str(fixture.backup_dir / name), str(fixture.live_dir / name)],
                       check=True, timeout=5)


def verify(client, **options):
    return action(client, "recovery.health.validate", dry_run=False, **options)


def test_native_copy_verification_brief_end_export_and_reset(native):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    before = files(fixture)
    receipt = verify(client)
    assert receipt.status_code == 200
    assert files(fixture) == before  # No marker deletion, staging cleanup or repair.
    view = client.get("/api/participant/recovery", headers=headers(SOC)).json()
    assert view["recovery"]["mode"] == "native_files"
    assert not view["recovery"]["portal_restore_allowed"]
    event = view["audit"][-1]
    assert event["event_type"] == "recovery.files.verified"
    assert event["run_id"] == service.run.run_id
    assert event["data"]["verification_method"] == "controller_read_only_filesystem"
    assert event["data"]["requested_by"] == "recovery-learner"
    assert event["data"]["checks"]["live_files_match"]
    assert not event["data"]["permissions_verified"]
    assert not event["data"]["intended_user_access_verified"]
    assert not event["data"]["learner_attribution_verified"]
    assert str(fixture.approved_root) not in str(view)
    assert view["fixture"]["marker_count"] == 5
    assert not view["fixture"]["baseline_verified"]  # Preserved evidence is not a reset.
    assert client.post("/api/participant/recovery/brief", headers=headers(SOC),
                       json=payload(service)).status_code == 200
    advance(client, 7800)
    assert service.run.controller.state.value == "completed"
    assert service.run.impact.final_review.passed
    assert service.run.impact.final_review.checks["native_file_observation_current"]
    ledger = service.store.events(service.run.definition.exercise_id, service.run.run_id)
    for record in ledger:
        EventValidator().validate(record)
    exported = client.get("/api/facilitator/exports/events.jsonl", headers=headers(STAFF))
    assert event["event_id"] in exported.text and "controller_read_only_filesystem" in exported.text
    old_run = service.run.run_id
    reset = client.post("/api/facilitator/reset", headers=headers(STAFF),
                        json={"new_run_id": "native-fresh"})
    assert reset.status_code == 200
    assert fixture.inspect()["baseline_verified"]
    assert service.run.recovery_mode == service.run.impact.recovery_mode == "native_files"
    assert service.run.impact.validation_event_id is None
    assert service.run.impact.native_validation_manifest is None
    assert service.run.impact.fixture.inspect()["baseline_verified"]
    assert service.store.events(service.run.definition.exercise_id, old_run)


@pytest.mark.parametrize("preview", [True, False])
def test_portal_cannot_restore_native_files_even_with_direct_http(native, preview):
    client, service = native
    fixture = service.run.impact.fixture
    before = files(fixture)
    assert action(client, dry_run=preview).status_code == 403
    assert files(fixture) == before
    assert service.run.impact.validation_event_id is None


def test_preview_does_not_validate_or_modify_restored_files(native):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    before = files(fixture)
    preview = action(client, "recovery.health.validate", dry_run=True)
    assert preview.status_code == 200 and preview.json()["status"] == "dry_run"
    assert service.run.impact.validation_event_id is None
    assert files(fixture) == before


@pytest.mark.parametrize("problem", ["missing", "partial", "corrupt-live", "corrupt-backup", "corrupt-staging"])
def test_incomplete_or_corrupt_restoration_never_gets_credit(native, problem):
    client, service = native
    fixture = service.run.impact.fixture
    if problem != "missing":
        native_copy(fixture)
    if problem == "partial":
        (fixture.live_dir / "billing-export.csv").unlink()
    elif problem.startswith("corrupt-"):
        section = {"corrupt-live": fixture.live_dir, "corrupt-backup": fixture.backup_dir,
                   "corrupt-staging": fixture.staging_dir}[problem]
        (section / "billing-export.csv").write_bytes(b"incorrect synthetic bytes")
    before = files(fixture)
    assert verify(client).status_code == 403
    assert files(fixture) == before
    assert service.run.impact.validation_event_id is None
    assert not service.run.impact.evaluate_recovery().passed


@pytest.mark.parametrize("problem", ["symlink", "hardlink", "fifo", "directory", "oversized", "unexpected"])
def test_unsafe_native_files_are_refused_without_following_or_repairing(native, tmp_path, problem):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside must not change")
    target = fixture.live_dir / "billing-export.csv"
    target.unlink()
    if problem == "symlink":
        target.symlink_to(outside)
    elif problem == "hardlink":
        os.link(outside, target)
    elif problem == "fifo":
        os.mkfifo(target)
    elif problem == "directory":
        target.mkdir()
    elif problem == "oversized":
        target.write_bytes(b"x" * (64 * 1024 + 1))
    else:
        shutil.copyfile(fixture.backup_dir / target.name, target)
        (fixture.live_dir / "unapproved.txt").write_bytes(b"unexpected")
    assert verify(client).status_code == 403
    assert service.run.impact.validation_event_id is None
    assert outside.read_bytes() == b"outside must not change"
    stopped = client.post("/api/facilitator/stop", headers=headers(STAFF), json={"reason": "unsafe fixture"})
    assert stopped.status_code == 200


def test_replaced_file_between_stat_and_open_is_refused(native, tmp_path, monkeypatch):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside must not be read")
    target = fixture.live_dir / "billing-export.csv"
    real_open = MODULE.os.open
    replaced = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == target.name and not replaced:
            replaced = True
            target.unlink()
            target.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(MODULE.os, "open", racing_open)
    assert verify(client).status_code == 403
    assert replaced and service.run.impact.validation_event_id is None


def test_unauthorized_verification_cannot_erase_valid_evidence(native):
    client, service = native
    native_copy(service.run.impact.fixture)
    assert verify(client).status_code == 200
    identifier = service.run.impact.validation_event_id
    assert verify(client, token=SOC, key="unauthorized").status_code == 403
    assert service.run.impact.validation_event_id == identifier


def test_changed_files_cannot_reuse_an_old_verification_at_finish(native):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    assert verify(client).status_code == 200
    assert client.post("/api/participant/recovery/brief", headers=headers(SOC),
                       json=payload(service)).status_code == 200
    (fixture.live_dir / "billing-export.csv").write_bytes(b"modified after verification")
    advance(client, 7800)
    assert not service.run.impact.final_review.passed
    assert not service.run.impact.final_review.checks["native_file_observation_current"]


def test_wrong_run_and_learner_claims_cannot_authorize_verification(native):
    client, service = native
    native_copy(service.run.impact.fixture)
    body = {"action_id": "recovery.health.validate", "fixture_id": FIXTURE,
            "key": "stale", "dry_run": False}
    stale = client.post("/api/participant/recovery/action", json=body,
                        headers={**headers(RECOVERY), "X-Exercise-Run-ID": "old-run"})
    assert stale.status_code == 409
    assert service.run.impact.validation_event_id is None

    for extra in ({"passed": True}, {"path": str(Path("/outside"))},
                  {"mode": "fixture"}, {"permissions_verified": True}):
        response = client.post("/api/participant/recovery/action", headers=headers(RECOVERY),
                               json={**body, **extra})
        assert response.status_code == 422
    assert service.run.impact.validation_event_id is None


def test_file_changed_while_reading_is_refused(native, monkeypatch):
    client, service = native
    fixture = service.run.impact.fixture
    native_copy(fixture)
    target = fixture.live_dir / "billing-export.csv"
    identifier = target.stat().st_ino
    real_fstat = MODULE.os.fstat
    reads = 0

    def racing_fstat(descriptor):
        nonlocal reads
        value = real_fstat(descriptor)
        if value.st_ino == identifier:
            reads += 1
            if reads == 2:
                target.write_bytes(b"modified during verification")
                return real_fstat(descriptor)
        return value

    monkeypatch.setattr(MODULE.os, "fstat", racing_fstat)
    assert verify(client).status_code == 403
    assert reads >= 2 and service.run.impact.validation_event_id is None


def test_native_verification_after_stop_cannot_change_recorded_observation(native):
    client, service = native
    native_copy(service.run.impact.fixture)
    assert verify(client).status_code == 200
    identifier = service.run.impact.validation_event_id
    assert client.post("/api/facilitator/stop", headers=headers(STAFF),
                       json={"reason": "end native drill"}).status_code == 200
    assert verify(client, key="after-stop").status_code == 409
    assert service.run.impact.validation_event_id == identifier
