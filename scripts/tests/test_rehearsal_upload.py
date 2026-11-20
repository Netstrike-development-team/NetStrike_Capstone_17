"""Fail-closed safety for the bounded generated rehearsal artifact only."""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

from orchestrator import impact
from scripts import check_rehearsal_upload as guard


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "generated"
    disposable = root / "path-pass-pass-pass-pass" / "disposable"
    disposable.mkdir(parents=True)
    (disposable / guard.ROOT_MARKER).write_bytes(guard.ROOT_CONTENT)
    (root / "failure.json").write_text('{"synthetic":true}')
    return root


def test_marker_allowlist_matches_actual_producer():
    assert guard.ROOT_MARKER == impact.ROOT_MARKER
    assert guard.ROOT_CONTENT == impact.ROOT_CONTENT


def test_valid_partial_diagnostics_are_uploadable_without_claiming_success(evidence):
    before = {p.relative_to(evidence): p.read_bytes() for p in evidence.rglob("*") if p.is_file()}
    receipt = guard.inspect_upload(evidence)
    assert receipt["upload_safe"] and receipt["hidden_root_markers"] == 1
    assert receipt["files_checked"] == 2
    assert "verified" not in receipt and "range_acceptance" not in receipt
    assert before == {p.relative_to(evidence): p.read_bytes() for p in evidence.rglob("*") if p.is_file()}


@pytest.mark.parametrize("relative", [
    ".env", ".git/config", ".DS_Store", "case/.env", "case/.credentials/key",
    f"{guard.ROOT_MARKER}", f"case/{guard.ROOT_MARKER}",
    f"case/disposable/run/{guard.ROOT_MARKER}",
    f".private/disposable/{guard.ROOT_MARKER}",
])
def test_unrelated_or_misplaced_hidden_files_are_refused(evidence, relative):
    file = evidence / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(guard.ROOT_CONTENT)
    with pytest.raises(ValueError, match="hidden"):
        guard.inspect_upload(evidence)


def test_empty_hidden_directory_is_refused(evidence):
    (evidence / ".git").mkdir()
    with pytest.raises(ValueError, match="hidden"):
        guard.inspect_upload(evidence)


def test_wrong_marker_content_is_refused(evidence):
    marker = evidence / "path-pass-pass-pass-pass/disposable" / guard.ROOT_MARKER
    marker.write_bytes(b"not the fixed synthetic marker")
    with pytest.raises(ValueError, match="content"):
        guard.inspect_upload(evidence)


def test_marker_directory_is_refused(evidence):
    marker = evidence / "path-pass-pass-pass-pass/disposable" / guard.ROOT_MARKER
    marker.unlink()
    marker.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        guard.inspect_upload(evidence)


@pytest.mark.parametrize("kind", ["root", "file", "directory", "dangling", "hardlink", "fifo"])
def test_links_and_special_files_are_refused(evidence, tmp_path, kind):
    outside = tmp_path / "outside"
    outside.write_text("synthetic external test data")
    root = evidence
    if kind == "root":
        root = tmp_path / "root-link"
        root.symlink_to(evidence, target_is_directory=True)
    elif kind == "hardlink":
        os.link(outside, evidence / "linked-file")
    elif kind == "fifo":
        os.mkfifo(evidence / "pipe")
    elif kind == "directory":
        (evidence / "external-dir").symlink_to(tmp_path, target_is_directory=True)
    else:
        (evidence / "external-file").symlink_to(outside if kind == "file" else tmp_path / "absent")
    with pytest.raises(ValueError, match="real directory|links|regular unlinked"):
        guard.inspect_upload(root)


@pytest.mark.parametrize("limit", ["MAX_ENTRIES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES"])
def test_size_and_entry_limits_fail_closed(evidence, monkeypatch, limit):
    monkeypatch.setattr(guard, limit, 1)
    with pytest.raises(ValueError, match="limit"):
        guard.inspect_upload(evidence)


def test_missing_or_empty_roots_are_refused(tmp_path):
    with pytest.raises(ValueError, match="real directory"):
        guard.inspect_upload(tmp_path / "missing")
    with pytest.raises(ValueError, match="no files"):
        guard.inspect_upload(tmp_path)


def test_cli_works_without_site_packages_and_fails_closed(evidence):
    script = ROOT / "scripts/check_rehearsal_upload.py"
    command = [sys.executable, "-S", str(script), str(evidence)]
    success = subprocess.run(command, capture_output=True, text=True, check=False)
    assert success.returncode == 0 and json.loads(success.stdout)["upload_safe"]
    (evidence / ".env").write_text("synthetic test content, not credentials")
    failure = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failure.returncode == 2 and not json.loads(failure.stdout)["upload_safe"]
    assert "synthetic test content" not in failure.stdout


def test_archive_preserves_empty_directories_and_all_original_bytes(evidence, tmp_path):
    (evidence / "case-empty/staging").mkdir(parents=True)
    target = tmp_path / "evidence.tar.gz"
    receipt = guard.package_upload(evidence, target)
    assert receipt["archive_created"] and len(receipt["archive_sha256"]) == 64
    unpacked = tmp_path / "unpacked"
    with tarfile.open(target) as archive:
        archive.extractall(unpacked, filter="data")
    assert {p.relative_to(evidence) for p in evidence.rglob("*")} == {
        p.relative_to(unpacked) for p in unpacked.rglob("*")
    }
    for file in evidence.rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (unpacked / file.relative_to(evidence)).read_bytes()


@pytest.mark.parametrize("kind", ["existing", "symlink", "inside-input", "unsafe-input"])
def test_archive_refuses_unsafe_input_and_overwrites(evidence, tmp_path, kind):
    target = tmp_path / "evidence.tar.gz"
    unrelated = tmp_path / "notes"
    unrelated.write_text("preserve synthetic test notes")
    if kind == "existing":
        target.write_text("preserve existing output")
    elif kind == "symlink":
        target.symlink_to(unrelated)
    elif kind == "inside-input":
        target = evidence / "archive.tar.gz"
    else:
        (evidence / ".env").write_text("synthetic content")
    with pytest.raises((ValueError, FileExistsError)):
        guard.package_upload(evidence, target)
    assert unrelated.read_text() == "preserve synthetic test notes"
    if kind == "existing":
        assert target.read_text() == "preserve existing output"
    elif kind in {"inside-input", "unsafe-input"}:
        assert not target.exists()


def test_cli_archiving_is_explicit_and_dependency_free(evidence, tmp_path):
    target = tmp_path / "cli-evidence.tar.gz"
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "scripts/check_rehearsal_upload.py"),
         str(evidence), "--archive", str(target)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0 and json.loads(result.stdout)["archive_created"]
    assert target.is_file()


def test_archive_upload_is_guarded_and_scoped_only_to_generated_full_play_evidence():
    workflow = yaml.safe_load((ROOT / ".github/workflows/local-rehearsal-ci.yml").read_text())
    steps = workflow["jobs"]["full-play-rehearsal"]["steps"]
    check = next(s for s in steps if s.get("id") == "rehearsal_upload_safety")
    packaging = next(s for s in steps if s.get("id") == "rehearsal_archive")
    upload = next(s for s in steps if s.get("name") == "Retain synthetic developer evidence (not range sign-off)")
    assert check["if"] == "always()"
    assert check["run"] == 'python scripts/check_rehearsal_upload.py "$RUNNER_TEMP/local-rehearsal-evidence"'
    assert "continue-on-error" not in check and "||" not in check["run"]
    assert packaging["if"] == "always() && steps.rehearsal_upload_safety.outcome == 'success'"
    assert packaging["run"] == (
        'python scripts/check_rehearsal_upload.py "$RUNNER_TEMP/local-rehearsal-evidence" '
        '--archive "$RUNNER_TEMP/local-rehearsal-evidence.tar.gz"'
    )
    assert "continue-on-error" not in packaging
    assert upload["if"] == "always() && steps.rehearsal_archive.outcome == 'success'"
    assert upload["with"]["path"] == "${{ runner.temp }}/local-rehearsal-evidence.tar.gz"
    assert steps.index(check) < steps.index(packaging) < steps.index(upload)
    enabled = [(job, step) for job, config in workflow["jobs"].items() for step in config["steps"]
               if step.get("with", {}).get("include-hidden-files")]
    assert enabled == []
