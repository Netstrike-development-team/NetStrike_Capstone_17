import io
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from tarfile import TarInfo

import pytest

from scripts import offline_bundle
from scripts.offline_bundle import (
    _copy_linux_package_archives,
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


def test_wheel_inventory_uses_license_classifiers_and_author_emails(tmp_path: Path):
    wheel = tmp_path / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: demo\n"
            "Version: 1.0\n"
            "Classifier: License :: OSI Approved :: MIT License\n"
            "Author-email: =?utf-8?q?Jos=C3=A9_Example?= <jose@example.com>\n",
        )

    artifact = offline_bundle._wheel_inventory(wheel)

    assert artifact["license"] == "MIT"
    assert artifact["owner"] == "José Example"


def test_wheel_inventory_identifies_bsd_variant_from_license_file(tmp_path: Path):
    wheel = tmp_path / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: demo\n"
            "Version: 1.0\n"
            "Classifier: License :: OSI Approved :: BSD License\n",
        )
        archive.writestr(
            "demo-1.0.dist-info/licenses/LICENSE.txt",
            "Redistribution and use in source and binary forms are permitted.\n"
            "Neither the name of the copyright holder nor the names of its "
            "contributors may be used to endorse products.\n",
        )

    artifact = offline_bundle._wheel_inventory(wheel)

    assert artifact["license"] == "BSD-3-Clause"


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
        assert entry["license"] == "Not separately declared for bundled project source"
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
    package_dir = tmp_path / "linux-package-download"
    package_dir.mkdir()

    for package in offline_bundle.LINUX_DOMAIN_PACKAGES:
        (package_dir / f"{package}_1.0_amd64.deb").write_bytes(b"package")

    def package_metadata(command, **kwargs):
        package_name = Path(command[-1]).name.split("_", 1)[0]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{package_name}\n1.0\namd64\nUbuntu Maintainers\n",
        )

    monkeypatch.setattr(
        offline_bundle.subprocess,
        "run",
        package_metadata,
    )
    package_inventory = _copy_linux_package_archives(package_dir, bundle, "CTRL01")

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
        "linux_packages": package_inventory,
        "source_artifacts": source_inventory,
        "ansible_collections": [],
    }
    offline_bundle._verify_inventory_artifacts(bundle, inventory)

    bundled_package = bundle / package_inventory[0]["file"]
    bundled_package.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="inventory SHA-256 mismatch: adcli"):
        offline_bundle._verify_inventory_artifacts(bundle, inventory)

    wheel.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="inventory SHA-256 mismatch: demo"):
        offline_bundle._verify_inventory_artifacts(bundle, inventory)


def test_downloads_linux_domain_packages_for_pinned_ubuntu_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        volume = command[command.index("--volume") + 1]
        package_dir = Path(volume.split(":", 1)[0])
        package_dir.mkdir(parents=True, exist_ok=True)
        for package in offline_bundle.LINUX_DOMAIN_PACKAGES:
            (package_dir / f"{package}_1.0_amd64.deb").touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(offline_bundle.subprocess, "run", fake_run)
    package_dir = tmp_path / "packages"

    offline_bundle._download_linux_packages(package_dir)

    assert commands[0][0:2] == ["docker", "run"]
    assert offline_bundle.LINUX_PACKAGE_IMAGE in commands[0]
    assert "apt-get install --download-only" in commands[0][-1]
    assert "Dir::Cache::archives=/packages" not in commands[0][-1]
    assert commands[0][-1].endswith(
        " && install -m 0644 /var/cache/apt/archives/*.deb /packages/"
    )
    assert all(
        (package_dir / f"{package}_1.0_amd64.deb").is_file()
        for package in offline_bundle.LINUX_DOMAIN_PACKAGES
    )


def test_linux_package_download_reports_container_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        offline_bundle.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 100),
    )

    with pytest.raises(RuntimeError, match="download failed with exit code 100"):
        offline_bundle._download_linux_packages(tmp_path / "packages")


def test_linux_package_download_rejects_missing_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        offline_bundle.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    with pytest.raises(ValueError, match="apt produced no Linux domain package archives"):
        offline_bundle._download_linux_packages(tmp_path / "packages")


def test_linux_package_verification_stages_archives_in_container_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(offline_bundle.subprocess, "run", run)

    offline_bundle._verify_linux_packages_offline(tmp_path, "CTRL01")

    command, = commands
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--volume") + 1] == (
        f"{tmp_path}/destinations/CTRL01/linux-packages:/packages:ro"
    )
    assert command[-1] == (
        "install -m 0644 /packages/*.deb /var/cache/apt/archives/ && "
        "apt-get install --no-download --no-install-recommends --yes "
        "/var/cache/apt/archives/*.deb"
    )


@pytest.mark.parametrize("architecture", ["amd64", "all"])
def test_linux_package_inventory_requests_unlabelled_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, architecture: str
):
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    monkeypatch.setattr(offline_bundle, "LINUX_DOMAIN_PACKAGES", ("adcli",))
    (package_dir / f"adcli_1.0_{architecture}.deb").write_bytes(b"package")

    def package_metadata(command, **kwargs):
        assert command == [
            "dpkg-deb",
            "--show",
            "--showformat=${Package}\\n${Version}\\n${Architecture}\\n${Maintainer}\\n",
            str(package_dir / f"adcli_1.0_{architecture}.deb"),
        ]
        return subprocess.CompletedProcess(
            command, 0, stdout=f"adcli\n1.0\n{architecture}\nUbuntu Maintainers\n"
        )

    monkeypatch.setattr(offline_bundle.subprocess, "run", package_metadata)

    inventory = _copy_linux_package_archives(package_dir, tmp_path / "bundle")

    assert inventory[0]["name"] == "adcli"
    assert inventory[0]["version"] == "1.0"
    assert inventory[0]["architecture"] == architecture
    assert inventory[0]["owner"] == "Ubuntu Maintainers"


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb is not installed")
def test_linux_package_inventory_reads_real_debian_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source"
    control = source / "DEBIAN"
    control.mkdir(parents=True)
    (control / "control").write_text(
        "Package: adcli\nVersion: 1.0\nArchitecture: amd64\n"
        "Maintainer: Example Maintainer <maintainer@example.invalid>\n"
        "Description: Offline bundle metadata test\n",
        encoding="utf-8",
    )
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    subprocess.run(
        ["dpkg-deb", "--build", str(source), str(package_dir / "adcli_1.0_amd64.deb")],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(offline_bundle, "LINUX_DOMAIN_PACKAGES", ("adcli",))

    inventory = _copy_linux_package_archives(package_dir, tmp_path / "bundle")

    assert inventory[0]["name"] == "adcli"
    assert inventory[0]["version"] == "1.0"
    assert inventory[0]["architecture"] == "amd64"
    assert inventory[0]["owner"] == "Example Maintainer <maintainer@example.invalid>"


def test_linux_package_inventory_rejects_unsupported_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    (package_dir / "adcli_1.0_arm64.deb").write_bytes(b"package")
    monkeypatch.setattr(
        offline_bundle.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="adcli\n1.0\narm64\nUbuntu Maintainers\n"
        ),
    )

    with pytest.raises(ValueError, match="unsupported Linux package architecture: arm64"):
        _copy_linux_package_archives(package_dir, tmp_path / "bundle")


def test_linux_package_inventory_requires_direct_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    (package_dir / "adcli_1.0_amd64.deb").write_bytes(b"package")

    def package_metadata(command, **kwargs):
        package_name = Path(command[-1]).name.split("_", 1)[0]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{package_name}\n1.0\namd64\nUbuntu Maintainers\n",
        )

    monkeypatch.setattr(
        offline_bundle.subprocess,
        "run",
        package_metadata,
    )

    with pytest.raises(ValueError, match="missing requested packages"):
        _copy_linux_package_archives(package_dir, tmp_path / "bundle", "CTRL01")


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


def test_collection_license_falls_back_to_copying_file(tmp_path: Path):
    archive_path = tmp_path / "microsoft.ad-1.12.1.tar.gz"
    manifest = {
        "collection_info": {
            "namespace": "microsoft",
            "name": "ad",
            "version": "1.12.1",
            "authors": ["Ansible Project"],
        }
    }
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = json.dumps(manifest).encode()
        member = TarInfo("MANIFEST.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
        copying = b"GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"
        member = TarInfo("COPYING")
        member.size = len(copying)
        archive.addfile(member, io.BytesIO(copying))

    inventory = _copy_ansible_collection_archives([str(archive_path)], tmp_path / "bundle")

    assert inventory[0]["license"] == "GNU GPL v3 (COPYING file; manifest license field absent)"
    assert inventory[0]["owner"] == "Ansible Project"


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
