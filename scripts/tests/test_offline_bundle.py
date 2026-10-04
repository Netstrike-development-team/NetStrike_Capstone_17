import io
import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from tarfile import TarInfo

import pytest

from scripts import offline_bundle
from scripts.offline_bundle import (
    _copy_ansible_collection_archives,
    _copy_source_directories,
    _configured_destination,
    _configured_runtime_url,
    _extract_archive,
    _runtime_version_from_environment,
    _safe_relative_path,
    _safe_archive_members,
    _validate_destination,
    _write_checksums,
    _write_lock_and_inventory,
)


SCRIPT = Path(__file__).resolve().parents[1] / "offline_bundle.py"


def make_bundle(tmp_path: Path, *, tamper: bool = False) -> Path:
    root = tmp_path / "netstrike-offline-bundle"
    (root / "destinations" / "ctrl01").mkdir(parents=True)
    payload = root / "destinations" / "ctrl01" / "requirements.lock"
    payload.write_text("example==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
    checksum = hashlib.sha256(payload.read_bytes()).hexdigest()
    (root / "SHA256SUMS").write_text(
        f"{checksum}  destinations/ctrl01/requirements.lock\n", encoding="utf-8"
    )
    if tamper:
        payload.write_text("changed\n", encoding="utf-8")
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(root, arcname=root.name)
    return archive


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../escape", "a/../../escape", r"..\escape", "C:/escape"]
)
def test_rejects_unsafe_archive_paths(path: str):
    with pytest.raises(ValueError, match="unsafe bundle path"):
        _safe_relative_path(path)


def test_inventory_records_acceptance_fields_and_bundle_checksums(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nLicense: MIT\n",
        )

    inventory = _write_lock_and_inventory([wheel], wheelhouse, "CTRL01")
    lock = (tmp_path / "requirements.lock").read_text(encoding="utf-8")
    _write_checksums(tmp_path)
    checksums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")

    assert inventory[0]["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert inventory[0]["destination_vm"] == "CTRL01"
    assert inventory[0]["offline_install_method"]
    assert inventory[0]["license"] == "MIT"
    assert inventory[0]["owner"] == "UNKNOWN (review required)"
    assert f"--hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}" in lock
    assert "wheelhouse/demo-1.0-py3-none-any.whl" in checksums
    assert "requirements.lock" in checksums


def test_copies_module_dashboard_and_ansible_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    for directory in offline_bundle.SOURCE_DIRECTORIES:
        source = repo / directory
        source.mkdir(parents=True)
        (source / "example.txt").write_text(directory, encoding="utf-8")
        (source / "__pycache__").mkdir()
        (source / "__pycache__" / "ignored.pyc").write_bytes(b"cache")
    monkeypatch.setattr(offline_bundle, "REPO_ROOT", repo)

    entries = _copy_source_directories(tmp_path / "bundle")

    assert [entry["name"] for entry in entries] == list(offline_bundle.SOURCE_DIRECTORIES)
    for directory in offline_bundle.SOURCE_DIRECTORIES:
        source_tree = tmp_path / "bundle" / "source" / directory
        assert (source_tree / "example.txt").read_text() == directory
        assert not list(source_tree.rglob("*.pyc"))
        entry = next(item for item in entries if item["name"] == directory)
        assert entry["sha256"] == offline_bundle._directory_sha256(source_tree)
        assert entry["destination_vm"] == "CTRL01"
        assert entry["offline_install_method"]
        assert entry["license"].startswith("UNKNOWN")
        assert entry["owner"] == "Netstrike-development-team"


def test_runtime_inventory_records_acceptance_fields(tmp_path: Path):
    archive = tmp_path / "bundle" / "runtime" / "python-runtime.tar.gz"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"runtime")

    inventory = offline_bundle._runtime_inventory(
        archive, "https://example.invalid/python-runtime.tar.gz", "3.11.16", "CTRL01"
    )

    assert inventory["name"] == "CPython portable runtime"
    assert inventory["version"] == "3.11.16"
    assert inventory["source"] == "https://example.invalid/python-runtime.tar.gz"
    assert inventory["sha256"] == hashlib.sha256(b"runtime").hexdigest()
    assert inventory["destination_vm"] == "CTRL01"
    assert inventory["offline_install_method"]
    assert inventory["license"]
    assert inventory["owner"]
    assert inventory["file"] == "runtime/python-runtime.tar.gz"


def test_inventory_verification_checks_required_fields_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    runtime_archive = bundle / "runtime" / "python-runtime.tar.gz"
    runtime_archive.parent.mkdir()
    runtime_archive.write_bytes(b"runtime")

    wheelhouse = bundle / "destinations" / "CTRL01" / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nLicense: MIT\n",
        )
    wheel_inventory = _write_lock_and_inventory(
        [wheel], wheelhouse, "CTRL01", bundle_root=bundle
    )

    repo = tmp_path / "repo"
    for directory in offline_bundle.SOURCE_DIRECTORIES:
        source = repo / directory
        source.mkdir(parents=True)
        (source / "example.txt").write_text(directory, encoding="utf-8")
    monkeypatch.setattr(offline_bundle, "REPO_ROOT", repo)
    source_inventory = _copy_source_directories(bundle, "test-revision", "CTRL01")

    inventory = {
        "destination_vm": "CTRL01",
        "python_runtime": offline_bundle._runtime_inventory(
            runtime_archive, "https://example.invalid/runtime", "3.11.16", "CTRL01"
        ),
        "artifacts": wheel_inventory,
        "source_artifacts": source_inventory,
        "ansible_collections": [],
    }
    offline_bundle._verify_inventory_artifacts(bundle, inventory)

    wheel.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="inventory SHA-256 mismatch: demo"):
        offline_bundle._verify_inventory_artifacts(bundle, inventory)


def test_copies_ansible_collections_and_records_manifest_metadata(tmp_path: Path):
    archive_path = tmp_path / "ansible.windows-3.8.0.tar.gz"
    manifest = {
        "collection_info": {
            "namespace": "ansible",
            "name": "windows",
            "version": "3.8.0",
            "authors": ["Ansible Project"],
            "license": ["GPL-3.0-or-later"],
        }
    }
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = json.dumps(manifest).encode()
        member = TarInfo("MANIFEST.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    inventory = _copy_ansible_collection_archives([str(archive_path)], tmp_path / "bundle")

    assert inventory == [
        {
            "name": "ansible.windows",
            "version": "3.8.0",
            "source": "Ansible Galaxy",
            "license": "GPL-3.0-or-later",
            "owner": "Ansible Project",
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "destination_vm": "CTRL01",
            "offline_install_method": (
                "Install the bundled collection archive with ansible-galaxy collection "
                "install --offline and a local collections path."
            ),
            "file": "ansible/collections/ansible.windows-3.8.0.tar.gz",
        }
    ]
    assert (
        tmp_path / "bundle" / inventory[0]["file"]
    ).read_bytes() == archive_path.read_bytes()


def test_workflow_configuration_is_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFFLINE_BUNDLE_DESTINATION", raising=False)
    monkeypatch.delenv("OFFLINE_BUNDLE_PYTHON_VERSION", raising=False)
    monkeypatch.delenv("OFFLINE_BUNDLE_PYTHON_URL", raising=False)

    with pytest.raises(ValueError, match="OFFLINE_BUNDLE_DESTINATION is required"):
        _configured_destination()
    with pytest.raises(ValueError, match="OFFLINE_BUNDLE_PYTHON_VERSION is required"):
        _runtime_version_from_environment()
    with pytest.raises(ValueError, match="OFFLINE_BUNDLE_PYTHON_URL is required"):
        _configured_runtime_url()


@pytest.mark.parametrize("destination", ["../escape", "CTRL/01", ""])
def test_rejects_invalid_bundle_destination(destination: str):
    with pytest.raises(ValueError, match="destination contains invalid characters"):
        _validate_destination(destination)


def test_archive_rejects_links_outside_root(tmp_path: Path):
    archive_path = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        link = TarInfo("python/bin/python")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../../tmp/escape"
        archive.addfile(link)

    with tarfile.open(archive_path, "r:gz") as archive:
        with pytest.raises(ValueError, match="escapes its root"):
            _safe_archive_members(archive, "python", allow_links=True)


def test_archive_rejects_path_traversal(tmp_path: Path):
    archive_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = TarInfo("bundle/../../escape")
        member.type = tarfile.REGTYPE
        archive.addfile(member)

    with pytest.raises(ValueError, match="unsafe bundle path"):
        _extract_archive(archive_path, tmp_path / "extract", "bundle")


def test_archive_rejects_duplicate_normalized_paths(tmp_path: Path):
    archive_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("bundle/file", "bundle/file/"):
            member = TarInfo(name)
            member.type = tarfile.DIRTYPE if name.endswith("/") else tarfile.REGTYPE
            archive.addfile(member)

    with tarfile.open(archive_path, "r:gz") as archive:
        with pytest.raises(ValueError, match="duplicate archive path"):
            _safe_archive_members(archive, "bundle", allow_links=False)


def test_verify_checks_bundle_checksums(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "verify", str(make_bundle(tmp_path)), "--check-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "checksums are valid" in result.stdout


def test_verify_rejects_modified_bundle_file(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "verify", str(make_bundle(tmp_path, tamper=True)), "--check-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
