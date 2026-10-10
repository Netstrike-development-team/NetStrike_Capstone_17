"""Inert staff CLI and shared harness contracts; actual journey runs separately in CI."""

from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from scripts import record_ui_walkthrough as recording
from scripts import rehearsal
from scripts.staff_browser_smoke import StaffWalkthrough

SCRIPT = Path(__file__).resolve().parents[1] / "staff_browser_smoke.py"


def test_staff_preview_needs_no_site_packages_and_makes_no_output(tmp_path):
    output = tmp_path / "not-created"
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    preview = json.loads(result.stdout)
    assert preview["preview_only"] and preview["writes_performed"] is False
    assert preview["journey_id"] == "staff-operations"
    assert len(preview["chapters"]) == 14
    assert not output.exists()


@pytest.mark.parametrize("arguments", [[], ["--fast"], ["--smoke-only"]])
def test_staff_execution_requires_explicit_output(arguments):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--execute", *arguments],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and "requires a new --output" in result.stderr


def test_staff_existing_output_is_preserved(tmp_path):
    artifact = tmp_path / "existing.txt"
    artifact.write_text("preserve user data")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--execute", "--output", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and "must not already exist" in result.stderr
    assert artifact.read_text() == "preserve user data"


def test_staff_cli_delegates_to_shared_smoke_harness(tmp_path, monkeypatch):
    calls = []

    def record(self):
        calls.append((self.output, self.smoke_only, self.fast, self.narrate))

    monkeypatch.setattr(StaffWalkthrough, "record", record)
    output = tmp_path / "new"
    recording.main(["--execute", "--output", str(output)], walkthrough_type=StaffWalkthrough)
    assert calls == [(output, True, True, False)]
    assert not list(output.iterdir())


def test_staff_roles_are_fresh_and_no_checks_are_claimed_before_play(tmp_path):
    staff = StaffWalkthrough(tmp_path, smoke_only=True)
    other = StaffWalkthrough(tmp_path, smoke_only=True)
    assert set(staff.roles) == set(recording.Walkthrough.role_names) | {"technical_operator", "evaluator"}
    assert not set(staff.roles.values()) & set(other.roles.values())
    assert staff.completed_checks == {} and staff.evidence_files == []
    with pytest.raises(AssertionError, match="journey assertions did not complete"):
        staff.smoke_receipt()
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize("status", [200, 409, 503])
def test_browser_post_requires_actual_success_and_returns_exact_body(tmp_path, status):
    recorder = StaffWalkthrough(tmp_path, smoke_only=True)
    calls = []
    request = SimpleNamespace(method="POST", post_data_json={"run_id": "test"})
    response = SimpleNamespace(url="http://127.0.0.1:1234/api/test", request=request,
                               status=status, json=lambda: {"revision": 1})

    def expect_response(predicate):
        assert predicate(response)
        assert not predicate(SimpleNamespace(url=response.url, request=SimpleNamespace(method="GET")))
        return nullcontext(SimpleNamespace(value=response))

    recorder.page = SimpleNamespace(
        expect_response=expect_response,
        locator=lambda selector: SimpleNamespace(click=lambda: calls.append(selector)),
    )
    if status == 200:
        assert recorder.browser_post("#save", "/api/test") == ({"revision": 1}, {"run_id": "test"})
    else:
        with pytest.raises(AssertionError, match="browser POST failed"):
            recorder.browser_post("#save", "/api/test")
    assert calls == ["#save"]


def test_staff_downloads_join_shared_artifact_hash_inventory(tmp_path, monkeypatch):
    (tmp_path / "frames").mkdir()
    recorder = StaffWalkthrough(tmp_path, smoke_only=True)
    recorder.page = SimpleNamespace(
        expect_download=lambda: nullcontext(SimpleNamespace(value=SimpleNamespace(
            save_as=lambda path: path.write_bytes(b"synthetic artifact fixture")
        ))),
        locator=lambda _selector: SimpleNamespace(click=lambda: None),
    )
    recorder.download("#archive-events", "events.jsonl")
    recorder.download("#bundle", "current-bundle.json")
    recorder.download("#after-reset", "after-reset-bundle.json")
    recorder.source = {"git_revision": "test", "working_tree_dirty": False, "files_sha256": {}}
    recorder.browser_version = "test-browser"
    recorder.events_count = 1
    recorder.completed_checks = {"play_completed": False, "synthetic_review_fixture": True,
                                 "learner_evaluation_performed": False, "archive_after_reset_checked": True}
    monkeypatch.setattr(recording.importlib.metadata, "version", lambda _: "test-package")
    recorder.smoke_receipt()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["journey_id"] == "staff-operations"
    assert manifest["play_completed"] is False and manifest["learner_evaluation_performed"] is False
    assert manifest["range_acceptance"] is False
    assert set(manifest["files_sha256"]) == {"events.jsonl", "current-bundle.json", "after-reset-bundle.json"}
    for name, digest in manifest["files_sha256"].items():
        assert digest == rehearsal._sha(tmp_path / name)


def test_existing_browser_job_strictly_runs_both_journeys_and_keeps_both_outputs():
    workflow = (rehearsal.ROOT / ".github/workflows/local-rehearsal-ci.yml").read_text()
    job = yaml.safe_load(workflow)["jobs"]["browser-smoke"]
    scenario = next(step for step in job["steps"] if "--smoke-only" in step.get("run", ""))
    staff = next(step for step in job["steps"] if "staff_browser_smoke.py" in step.get("run", ""))
    assert job["steps"].index(scenario) < job["steps"].index(staff)
    assert "if" not in staff and "continue-on-error" not in staff
    assert "--execute --output" in staff["run"] and "||" not in staff["run"]
    upload = next(step for step in job["steps"] if "upload-artifact@" in step.get("uses", ""))
    assert upload["if"] == "always()" and upload["with"]["retention-days"] == 14
    assert "browser-smoke-evidence/" in upload["with"]["path"]
    assert "staff-browser-smoke-evidence/" in upload["with"]["path"]
    assert job["timeout-minutes"] == 10
    fingerprints = rehearsal._source()["files_sha256"]
    for name in ("scripts/staff_browser_smoke.py", "scripts/tests/test_staff_browser_smoke.py",
                 "scripts/record_ui_walkthrough.py", ".github/workflows/local-rehearsal-ci.yml"):
        assert fingerprints[name] == rehearsal._sha(rehearsal.ROOT / name)
