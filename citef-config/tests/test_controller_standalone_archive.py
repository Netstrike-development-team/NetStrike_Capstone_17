"""Exercise standalone archive staging without changing the local host."""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "citef-config/roles/controller_service_standalone"
ANSIBLE = shutil.which("ansible-playbook")


def make_bundle(tmp_path, *, corrupt=False, checksums=True):
    bundle = tmp_path / "netstrike-offline-bundle"
    bundle.mkdir()
    payload = b"synthetic bundle payload"
    (bundle / "payload").write_bytes(payload)
    if checksums:
        digest = hashlib.sha256(b"wrong" if corrupt else payload).hexdigest()
        (bundle / "SHA256SUMS").write_text(f"{digest}  payload\n")
    archive_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(bundle, arcname=bundle.name)
    return archive_path


@pytest.mark.skipif(ANSIBLE is None, reason="ansible-playbook is not installed")
@pytest.mark.parametrize(
    ("corrupt", "checksums", "missing", "expected_task"),
    [
        (False, True, False, "Require runtime-injected portal credentials and TLS key"),
        (True, True, False, "Verify the controller bundle checksums"),
        (False, False, False, "Verify the controller bundle checksums"),
        (False, True, True, "Extract the controller bundle archive"),
    ],
)
def test_archive_is_verified_before_deployment_and_staging_is_removed(
    tmp_path, corrupt, checksums, missing, expected_task
):
    archive = make_bundle(tmp_path, corrupt=corrupt, checksums=checksums)
    if missing:
        archive.unlink()
    staging = tmp_path / "remote-tmp"
    staging.mkdir()
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "environment": {"TMPDIR": str(staging)},
        "vars": {
            "ansible_python_interpreter": sys.executable,
            "controller_bundle_archive": str(archive),
            "deployment_version": "test-version",
            "exercise_run_id": "test-run-id",
        },
        "roles": ["controller_service_standalone"],
    }]))
    env = os.environ.copy()
    env["ANSIBLE_ROLES_PATH"] = str(ROLE.parent)
    result = subprocess.run(
        [ANSIBLE, "-i", "localhost,", str(playbook)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_task in result.stdout, result.stdout + result.stderr
    assert "Create the staff group" not in result.stdout
    if corrupt or not checksums or missing:
        assert "Require runtime-injected portal credentials" not in result.stdout
    assert "Remove temporary controller bundle staging directory" in result.stdout
    assert not list(staging.glob("netstrike-controller-bundle-*"))


def test_deployment_uses_source_runtime_and_wheelhouse_from_extracted_bundle():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    block = next(task["block"] for task in tasks if "block" in task)
    paths = next(task["ansible.builtin.set_fact"] for task in block
                 if task["name"] == "Define controller release and artifact paths")
    assert paths["controller_source_root"] == "{{ controller_bundle_root }}/source"
    for name in (
        "Copy the application source with owner and permissions",
        "Stage the portable Python runtime",
        "Stage the hash-pinned offline Python wheelhouse",
        "Stage the hash-pinned Python requirements lock",
    ):
        task = next(task for task in block if task["name"] == name)
        assert task["ansible.builtin.copy"]["remote_src"] is True


@pytest.mark.skipif(ANSIBLE is None, reason="ansible-playbook is not installed")
def test_staging_tasks_copy_from_target_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    for relative in (
        "source/dashboard/app.py", "source/modules/example.py",
        "source/shared/example.py", "source/orchestrator/example.py",
        "source/schemas/example.json", "runtime/python-runtime.tar.gz",
        "destinations/CTRL01/wheelhouse/package.whl",
        "destinations/CTRL01/requirements.lock",
    ):
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)

    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    block = next(task["block"] for task in tasks if "block" in task)
    destinations = {
        "Copy the application source with owner and permissions": str(tmp_path / "release") + "/",
        "Stage the portable Python runtime": str(tmp_path / "runtime.tar.gz"),
        "Stage the hash-pinned offline Python wheelhouse": str(tmp_path / "wheelhouse") + "/",
        "Stage the hash-pinned Python requirements lock": str(tmp_path / "requirements.lock"),
    }
    selected = []
    for task in block:
        if task["name"] not in destinations:
            continue
        task["ansible.builtin.copy"]["dest"] = destinations[task["name"]]
        task["ansible.builtin.copy"].pop("owner", None)
        task["ansible.builtin.copy"].pop("group", None)
        selected.append(task)
    playbook = tmp_path / "copy.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "ansible_python_interpreter": sys.executable,
            "controller_source_root": str(bundle / "source"),
            "controller_bundle_root": str(bundle),
            "controller_wheelhouse_path": str(bundle / "destinations/CTRL01/wheelhouse"),
        },
        "tasks": selected,
    }]))
    result = subprocess.run(
        [ANSIBLE, "-i", "localhost,", str(playbook)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "release/dashboard/app.py").read_text() == "source/dashboard/app.py"
    assert (tmp_path / "runtime.tar.gz").read_text() == "runtime/python-runtime.tar.gz"
    assert (tmp_path / "wheelhouse/package.whl").read_text() == "destinations/CTRL01/wheelhouse/package.whl"
    assert (tmp_path / "requirements.lock").read_text() == "destinations/CTRL01/requirements.lock"
