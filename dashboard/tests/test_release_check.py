"""Offline release-source consistency against the real builder's existing format."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys

import pytest

from dashboard import release_check
from scripts import offline_bundle

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
PRIVATE = "private-token-should-never-appear"


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for name in offline_bundle.SOURCE_DIRECTORIES:
        tree = repo / name
        (tree / "a").mkdir(parents=True)
        (tree / "a" / "child.py").write_text("nested source\n")
        (tree / "a.py").write_text("sibling source\n")
        (tree / "empty").mkdir()
    monkeypatch.setattr(offline_bundle, "REPO_ROOT", repo)
    root = tmp_path / "bundle"
    records = offline_bundle._copy_source_directories(root, REVISION, "CTRL01")
    inventory = {"repository_revision": REVISION, "destination_vm": "CTRL01",
                 "source_artifacts": records, "private_prose": PRIVATE}
    (root / "inventory.json").write_text(json.dumps(inventory))
    return root


def inventory_digest(root):
    return hashlib.sha256((root / "inventory.json").read_bytes()).hexdigest()


def inspect(root, **options):
    return release_check.inspect_release(
        root, expected_revision=options.get("revision", REVISION),
        expected_inventory_sha256=options.get("digest", inventory_digest(root)),
    )


def alter_inventory(root, operation):
    path = root / "inventory.json"
    value = json.loads(path.read_text())
    operation(value)
    path.write_text(json.dumps(value))


def test_builder_source_format_composes_with_read_only_inspector(bundle, monkeypatch):
    assert release_check.SOURCE_TREES == offline_bundle.SOURCE_DIRECTORIES
    before = {path: path.read_bytes() for path in bundle.rglob("*") if path.is_file()}

    def forbidden(*_args, **_kwargs):
        pytest.fail("release checker must not start a runtime, query Git or use network/SQLite")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    report = inspect(bundle)
    assert report["source_verified"] is True
    assert report["read_only"] is True
    assert report["scope"] == "selected_application_source_only"
    assert report["repository_revision"] == REVISION
    assert report["inventory_sha256"] == inventory_digest(bundle)
    assert len(report["source_artifacts"]) == 6
    assert not report["source_authenticity_verified"]
    assert not report["running_process_verified"]
    assert not report["external_readiness_verified"]
    assert not report["blockers"]
    assert PRIVATE not in json.dumps(report) and str(bundle) not in json.dumps(report)
    assert before == {path: path.read_bytes() for path in bundle.rglob("*") if path.is_file()}


@pytest.mark.parametrize("tree", release_check.SOURCE_TREES)
@pytest.mark.parametrize("mutation", ["changed", "extra", "missing"])
def test_each_source_tree_rejects_changed_extra_or_missing_bytes(bundle, tree, mutation):
    root = bundle / "source" / tree
    if mutation == "changed":
        (root / "a" / "child.py").write_text(PRIVATE)
    elif mutation == "extra":
        (root / "unexpected.py").write_text(PRIVATE)
    else:
        (root / "a.py").unlink()
    report = inspect(bundle)
    assert not report["source_verified"]
    assert report["blockers"] == [f"source_{tree}"]
    assert PRIVATE not in json.dumps(report)


def test_expected_inventory_digest_is_checked_before_parsing(bundle):
    expected = inventory_digest(bundle)
    (bundle / "inventory.json").write_text(PRIVATE)
    report = inspect(bundle, digest=expected)
    assert report["blockers"] == ["inventory_digest"]
    assert report["repository_revision"] is None
    assert PRIVATE not in json.dumps(report)


def test_read_errors_and_changed_files_are_safe(bundle, monkeypatch):
    original = release_check._read_regular

    def fail_source(path, maximum):
        if path.name == "child.py":
            raise OSError(PRIVATE)
        return original(path, maximum)

    monkeypatch.setattr(release_check, "_read_regular", fail_source)
    report = inspect(bundle)
    assert not report["source_verified"]
    assert PRIVATE not in json.dumps(report)


def test_file_change_during_read_is_rejected(bundle, monkeypatch):
    path = bundle / "source/dashboard/a.py"
    original = os.fstat
    calls = 0

    def changed(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text("changed source with a different size")
        return original(descriptor)

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(ValueError, match="changed"):
        release_check._read_regular(path, 1024)


@pytest.mark.parametrize("value", [None, True, "", PRIVATE, "A" * 40, "a" * 39, "a" * 41])
def test_invalid_expected_commit_fails_before_filesystem_reads(bundle, monkeypatch, value):
    expected = inventory_digest(bundle)

    def forbidden(*_args):
        pytest.fail("invalid expectations must not read files")

    monkeypatch.setattr(release_check, "_read_regular", forbidden)
    report = inspect(bundle, revision=value, digest=expected)
    assert report["blockers"] == ["expected_release_identity"]


@pytest.mark.parametrize("value", [None, True, PRIVATE, "F" * 64, "f" * 63, "f" * 65])
def test_invalid_expected_inventory_digest_fails_closed(bundle, value):
    assert inspect(bundle, digest=value)["blockers"] == ["expected_release_identity"]


@pytest.mark.parametrize("mutation", [
    "missing-record", "extra-record", "duplicate-record", "path", "hash", "entry-version",
    "entry-destination", "destination", "revision", "unknown-revision", "records-type",
])
def test_invalid_inventory_records_cannot_supply_release_identity(bundle, mutation):
    def mutate(value):
        records = value["source_artifacts"]
        if mutation == "missing-record":
            records.pop()
        elif mutation == "extra-record":
            records.append(deepcopy(records[0]))
        elif mutation == "duplicate-record":
            records[-1] = deepcopy(records[0])
        elif mutation == "path":
            records[0]["path"] = "../" + PRIVATE
        elif mutation == "hash":
            records[0]["sha256"] = PRIVATE
        elif mutation == "entry-version":
            records[0]["version"] = "b" * 40
        elif mutation == "entry-destination":
            records[0]["destination_vm"] = "OTHER01"
        elif mutation == "destination":
            value["destination_vm"] = PRIVATE + "/unsafe"
        elif mutation == "revision":
            value["repository_revision"] = PRIVATE
        elif mutation == "unknown-revision":
            value["repository_revision"] = "UNKNOWN (not a release build)"
        else:
            value["source_artifacts"] = {}

    alter_inventory(bundle, mutate)
    report = inspect(bundle)
    assert report["blockers"] == ["source_inventory"]
    assert not report["source_verified"]
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize("raw", ['[]', 'null', '{', '{"repository_revision": "a", "repository_revision": "b"}'])
def test_malformed_and_duplicate_inventory_is_safe(bundle, raw):
    (bundle / "inventory.json").write_text(raw)
    assert inspect(bundle)["blockers"] == ["source_inventory"]


def test_other_valid_commit_does_not_pass_expected_revision(bundle):
    report = inspect(bundle, revision="b" * 40)
    assert report["blockers"] == ["expected_repository_revision"]
    assert len(report["source_artifacts"]) == 6  # Hashes alone do not prove the requested commit.


@pytest.mark.parametrize("location", ["inventory", "source-root", "tree", "file", "directory", "empty-directory"])
def test_symlinks_never_supply_source_or_inventory_bytes(bundle, tmp_path, location):
    expected = inventory_digest(bundle)
    paths = {"inventory": bundle / "inventory.json", "source-root": bundle / "source",
             "tree": bundle / "source/dashboard", "file": bundle / "source/dashboard/a.py",
             "directory": bundle / "source/dashboard/a", "empty-directory": bundle / "source/dashboard/empty"}
    path = paths[location]
    moved = tmp_path / "outside"
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=moved.is_dir())
    report = inspect(bundle, digest=expected)
    assert not report["source_verified"]
    assert str(moved) not in json.dumps(report)


def test_symlink_bundle_root_is_rejected(bundle, tmp_path):
    link = tmp_path / "linked"
    link.symlink_to(bundle, target_is_directory=True)
    assert inspect(link)["blockers"] == ["inventory_digest"]


@pytest.mark.parametrize("location", ["inventory.json", "source/dashboard/a.py"])
def test_hardlinked_inputs_are_rejected(bundle, tmp_path, location):
    expected = inventory_digest(bundle)
    (tmp_path / "hardlink").hardlink_to(bundle / location)
    assert not inspect(bundle, digest=expected)["source_verified"]


def test_special_file_is_rejected_without_blocking(bundle):
    os.mkfifo(bundle / "source/dashboard/pipe")
    assert inspect(bundle)["blockers"] == ["source_dashboard"]


@pytest.mark.parametrize("limit,value", [
    ("MAX_INVENTORY_BYTES", 8), ("MAX_FILE_BYTES", 1), ("MAX_TREE_BYTES", 1),
    ("MAX_TREE_ENTRIES", 1), ("MAX_DEPTH", 0),
])
def test_bounded_inspection_fails_closed(bundle, monkeypatch, limit, value):
    expected = inventory_digest(bundle)
    monkeypatch.setattr(release_check, limit, value)
    assert not inspect(bundle, digest=expected)["source_verified"]


@pytest.mark.parametrize("entry", ["unexpected.py", "unexpected-directory"])
def test_uninventoried_top_level_source_is_rejected(bundle, entry):
    path = bundle / "source" / entry
    path.mkdir() if entry.endswith("directory") else path.write_text(PRIVATE)
    assert inspect(bundle)["blockers"] == ["source_root"]


def test_missing_source_tree_is_rejected(bundle):
    shutil.rmtree(bundle / "source/dashboard")
    assert inspect(bundle)["blockers"] == ["source_root"]


def test_cached_bytecode_is_not_silently_ignored(bundle):
    cache = bundle / "source/dashboard/__pycache__"
    cache.mkdir()
    (cache / "a.cpython-311.pyc").write_bytes(b"cached code")
    assert inspect(bundle)["blockers"] == ["source_dashboard"]


@pytest.mark.parametrize("options", [[], ["--unknown", PRIVATE], ["--bundle-root", PRIVATE]])
def test_cli_misuse_does_not_echo_values(options, capsys):
    with pytest.raises(SystemExit) as error:
        release_check.main(options)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out and PRIVATE not in output.err


def test_cli_success_and_safe_validation_failure(bundle, capsys):
    options = ["--bundle-root", str(bundle), "--expect-revision", REVISION,
               "--expect-inventory-sha256", inventory_digest(bundle)]
    assert release_check.main(options) == 0
    assert json.loads(capsys.readouterr().out)["source_verified"] is True
    options[-1] = PRIVATE
    assert release_check.main(options) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["source_verified"] is False
    assert PRIVATE not in output.out + output.err


def test_cli_runs_without_site_packages_or_application_environment(bundle, tmp_path):
    result = subprocess.run(
        [sys.executable, "-B", "-S", "-m", "dashboard.release_check",
         "--bundle-root", str(bundle), "--expect-revision", REVISION,
         "--expect-inventory-sha256", inventory_digest(bundle)],
        cwd=tmp_path, env={"PYTHONPATH": str(ROOT)}, capture_output=True, text=True,
        check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_verified"] is True


def test_real_source_copy_contains_a_dependency_free_runnable_checker(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_bundle, "REPO_ROOT", ROOT)
    root = tmp_path / "real-bundle"
    records = offline_bundle._copy_source_directories(root, REVISION, "CTRL01")
    (root / "inventory.json").write_text(json.dumps({
        "repository_revision": REVISION, "destination_vm": "CTRL01", "source_artifacts": records,
    }))
    assert (root / "source/dashboard/release_check.py").is_file()
    result = subprocess.run(
        [sys.executable, "-B", "-S", "-m", "dashboard.release_check",
         "--bundle-root", str(root), "--expect-revision", REVISION,
         "--expect-inventory-sha256", inventory_digest(root)],
        cwd=tmp_path, env={"PYTHONPATH": str(root / "source")},
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_verified"] is True
