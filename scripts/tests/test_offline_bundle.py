import hashlib
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from tarfile import TarInfo

import pytest

from scripts.offline_bundle import (
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


def test_inventory_uses_lock_and_bundle_checksums_without_repeating_metadata(tmp_path: Path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nLicense: MIT\n",
        )

    inventory = _write_lock_and_inventory([wheel], wheelhouse)
    lock = (tmp_path / "requirements.lock").read_text(encoding="utf-8")
    _write_checksums(tmp_path)
    checksums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")

    assert "sha256" not in inventory[0]
    assert "destination_vm" not in inventory[0]
    assert "offline_install_method" not in inventory[0]
    assert f"--hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}" in lock
    assert "wheelhouse/demo-1.0-py3-none-any.whl" in checksums
    assert "requirements.lock" in checksums


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
