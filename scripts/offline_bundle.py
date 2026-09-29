#!/usr/bin/env python3
"""Build and verify portable Python runtime and dependency bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS_NAME = "SHA256SUMS"
UNKNOWN = "UNKNOWN (review required)"


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or "\0" in value
        or ":" in value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe bundle path: {value}")
    return path


def _requirement_paths(values: list[str]) -> list[Path]:
    paths = []
    for value in values:
        path = (REPO_ROOT / value).resolve()
        if not path.is_relative_to(REPO_ROOT) or not path.is_file():
            raise ValueError(f"requirements file must exist inside the repository: {value}")
        paths.append(path)
    return paths


def _wheel_inventory(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError(f"expected one wheel METADATA file in {wheel.name}")
        metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_paths[0]))

    project_urls = metadata.get_all("Project-URL", [])
    source = next(
        (
            url.strip()
            for url in project_urls
            if url.partition(",")[0].strip().lower() in {"source", "repository"}
        ),
        metadata.get("Home-page", "Python package index (pip configuration)"),
    )
    license_name = metadata.get("License-Expression") or metadata.get("License") or UNKNOWN
    owner = metadata.get("Author") or metadata.get("Maintainer") or UNKNOWN
    return {
        "name": metadata.get("Name", UNKNOWN),
        "version": metadata.get("Version", UNKNOWN),
        "source": source,
        "license": license_name.strip(),
        "owner": owner.strip(),
        "file": f"wheelhouse/{wheel.name}",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_members(
    archive: tarfile.TarFile, expected_root: str, *, allow_links: bool
) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if not members:
        raise ValueError("archive is empty")
    names = set()
    for member in members:
        relative = _safe_relative_path(member.name)
        if relative.parts[0] != expected_root:
            raise ValueError(f"unexpected archive path: {member.name}")
        normalized_name = relative.as_posix()
        if normalized_name in names:
            raise ValueError(f"duplicate archive path: {member.name}")
        names.add(normalized_name)
        if member.isfile() or member.isdir():
            continue
        if not allow_links or not (member.issym() or member.islnk()):
            raise ValueError(f"unsupported archive entry: {member.name}")
        if member.issym() or member.islnk():
            link = member.linkname
            if not link or link.startswith("/") or "\\" in link or "\0" in link:
                raise ValueError(f"unsafe archive link: {member.name}")
            resolved = posixpath.normpath(
                link if member.islnk() else posixpath.join(posixpath.dirname(member.name), link)
            )
            if resolved == ".." or resolved.startswith("../") or resolved.split("/")[0] != expected_root:
                raise ValueError(f"archive link escapes its root: {member.name}")
    return members


def _extract_archive(
    archive_path: Path, target: Path, expected_root: str, *, allow_links: bool = False
) -> Path:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_archive_members(archive, expected_root, allow_links=allow_links)
        target.mkdir(parents=True, exist_ok=True)
        archive.extractall(path=target, members=members, filter="data")
    extracted_root = target / expected_root
    if not extracted_root.is_dir():
        raise ValueError(f"archive root is missing: {expected_root}")
    return extracted_root


def _extract_python_runtime(
    archive_path: Path, target: Path, expected_version: str | None = None
) -> tuple[Path, str]:
    runtime_root = _extract_archive(archive_path, target, "python", allow_links=True)
    python = runtime_root / "bin" / "python3.11"
    version = subprocess.run(
        [str(python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if expected_version and version != expected_version:
        raise ValueError(f"bundled Python reports {version}, expected {expected_version}")
    if not re.fullmatch(r"3\.11\.\d+", version):
        raise ValueError(f"unsupported bundled Python runtime version: {version}")
    return python, version


def _configured_destination() -> str:
    destination = os.environ.get("OFFLINE_BUNDLE_DESTINATION")
    if not destination:
        raise ValueError("OFFLINE_BUNDLE_DESTINATION is required")
    return _validate_destination(destination)


def _validate_destination(destination: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", destination):
        raise ValueError("destination contains invalid characters")
    return destination


def _configured_runtime_url() -> str:
    url = os.environ.get("OFFLINE_BUNDLE_PYTHON_URL", "")
    if not url:
        raise ValueError("OFFLINE_BUNDLE_PYTHON_URL is required")
    if not url.startswith("https://"):
        raise ValueError("OFFLINE_BUNDLE_PYTHON_URL must use HTTPS")
    return url


def _runtime_version_from_environment() -> str:
    version = os.environ.get("OFFLINE_BUNDLE_PYTHON_VERSION")
    if not version:
        raise ValueError("OFFLINE_BUNDLE_PYTHON_VERSION is required")
    if not re.fullmatch(r"3\.11\.\d+", version):
        raise ValueError("OFFLINE_BUNDLE_PYTHON_VERSION must be an exact Python 3.11 version")
    return version


def _write_lock_and_inventory(wheels: list[Path], wheelhouse: Path) -> list[dict]:
    by_name: dict[str, tuple[dict, str]] = {}
    for wheel in sorted(wheels):
        artifact = _wheel_inventory(wheel)
        normalized_name = re.sub(r"[-_.]+", "-", artifact["name"]).lower()
        prior = by_name.get(normalized_name)
        wheel_hash = _sha256(wheel)
        if prior and (
            prior[0]["version"] != artifact["version"] or prior[1] != wheel_hash
        ):
            raise ValueError(f"multiple versions or builds found for {artifact['name']}")
        by_name[normalized_name] = (artifact, wheel_hash)

    lock_lines = [
        f"{artifact['name']}=={artifact['version']} --hash=sha256:{wheel_hash}"
        for artifact, wheel_hash in sorted(
            by_name.values(), key=lambda item: item[0]["name"].lower()
        )
    ]
    (wheelhouse.parent / "requirements.lock").write_text(
        "\n".join(lock_lines) + "\n", encoding="utf-8"
    )
    return sorted(
        (item[0] for item in by_name.values()), key=lambda item: item["name"].lower()
    )


def _write_checksums(root: Path) -> None:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != CHECKSUMS_NAME:
            relative = path.relative_to(root).as_posix()
            entries.append(f"{_sha256(path)}  {relative}")
    (root / CHECKSUMS_NAME).write_text("\n".join(entries) + "\n", encoding="utf-8")


def build_bundle(args: argparse.Namespace) -> None:
    destination = _configured_destination()
    requirement_files = _requirement_paths(args.requirements)
    runtime_archive = Path(args.python_runtime_archive).resolve()
    if not runtime_archive.is_file():
        raise FileNotFoundError(runtime_archive)
    runtime_url = _configured_runtime_url()
    output = Path(args.output).resolve()
    if output.suffixes[-2:] != [".tar", ".gz"]:
        raise ValueError("output must end in .tar.gz")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="netstrike-offline-") as temporary:
        bundle = Path(temporary) / "netstrike-offline-bundle"
        destination_dir = bundle / "destinations" / destination
        wheelhouse = destination_dir / "wheelhouse"
        wheelhouse.mkdir(parents=True)
        runtime_dir = bundle / "runtime"
        runtime_dir.mkdir()

        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        bundled_runtime = runtime_dir / "python-runtime.tar.gz"
        shutil.copyfile(runtime_archive, bundled_runtime)
        runtime_python, runtime_version = _extract_python_runtime(
            bundled_runtime,
            Path(temporary) / "runtime-check",
            _runtime_version_from_environment(),
        )

        command = [
            str(runtime_python),
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--dest",
            str(wheelhouse),
        ]
        for requirement_file in requirement_files:
            command.extend(["--requirement", str(requirement_file)])
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if completed.returncode:
            raise RuntimeError(f"pip download failed with exit code {completed.returncode}")

        wheels = sorted(wheelhouse.glob("*.whl"))
        if not wheels:
            raise ValueError("pip produced no wheels; refusing to create an empty bundle")
        artifacts = _write_lock_and_inventory(wheels, wheelhouse)

        manifest = {
            "repository_revision": revision,
            "destination_vm": destination,
            "python_runtime": {
                "version": runtime_version,
                "source": runtime_url or "Source URL not provided",
                "license": "Python Software Foundation License; review the upstream distribution terms",
                "file": bundled_runtime.relative_to(bundle).as_posix(),
            },
            "requirements_inputs": [
                path.relative_to(REPO_ROOT).as_posix() for path in requirement_files
            ],
            "artifacts": artifacts,
        }
        (bundle / "inventory.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_checksums(bundle)
        with tarfile.open(output, "w:gz") as archive:
            archive.add(bundle, arcname=bundle.name)

    print(f"Created {output} with {len(artifacts)} Python packages for {destination}.")


def _extract_bundle(archive_path: Path, target: Path) -> Path:
    return _extract_archive(archive_path, target, "netstrike-offline-bundle")


def _verify_checksums(root: Path) -> None:
    checksum_file = root / CHECKSUMS_NAME
    if not checksum_file.is_file():
        raise ValueError(f"missing {CHECKSUMS_NAME}")
    expected = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        try:
            checksum, relative = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"invalid checksum entry: {line}") from error
        safe_path = _safe_relative_path(relative)
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError(f"invalid SHA-256 value for {relative}")
        if relative in expected:
            raise ValueError(f"duplicate checksum entry: {relative}")
        expected[relative] = checksum
        path = root.joinpath(*safe_path.parts)
        if not path.is_file() or _sha256(path) != checksum:
            raise ValueError(f"checksum mismatch or missing file: {relative}")

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != CHECKSUMS_NAME
    }
    if actual != set(expected):
        raise ValueError("checksum list does not cover exactly the bundle files")


def verify_bundle(args: argparse.Namespace) -> None:
    archive_path = Path(args.archive).resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    with tempfile.TemporaryDirectory(prefix="netstrike-verify-") as temporary:
        bundle = _extract_bundle(archive_path, Path(temporary))
        _verify_checksums(bundle)
        if args.check_only:
            print("Bundle checksums are valid.")
            return

        inventory = json.loads((bundle / "inventory.json").read_text(encoding="utf-8"))
        destination = _validate_destination(inventory["destination_vm"])
        destination_dir = bundle / "destinations" / destination
        runtime = inventory["python_runtime"]
        expected_version = runtime["version"]
        runtime_path = _safe_relative_path(runtime["file"])
        if runtime_path.parts[0] != "runtime":
            raise ValueError("Python runtime archive must be inside runtime/")
        runtime_archive = bundle.joinpath(*runtime_path.parts)
        runtime_root = Path(temporary) / "python-runtime"
        python, runtime_version = _extract_python_runtime(
            runtime_archive, runtime_root, expected_version
        )
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(destination_dir / "wheelhouse"),
            "--require-hashes",
            "-r",
            str(destination_dir / "requirements.lock"),
        ]
        env = os.environ.copy()
        env["PIP_NO_INDEX"] = "1"
        env["PIP_CONFIG_FILE"] = os.devnull
        subprocess.run(command, check=True, env=env)

    print(
        f"Checksums, Python {runtime_version}, and offline dependency installation "
        f"are valid for {destination}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="package Python runtime and dependencies")
    build.add_argument(
        "--requirements",
        action="append",
        required=True,
        help="repository-relative requirements file (repeat to combine manifests)",
    )
    build.add_argument("--output", required=True, help="new .tar.gz archive path")
    build.add_argument(
        "--python-runtime-archive",
        required=True,
        help="CPython standalone Linux x86_64 install-only .tar.gz archive",
    )
    build.set_defaults(handler=build_bundle)

    verify = commands.add_parser("verify", help="verify checksums and install without an index")
    verify.add_argument("archive", help="offline bundle .tar.gz archive")
    verify.add_argument(
        "--check-only",
        action="store_true",
        help="verify archive contents and checksums without creating a test environment",
    )
    verify.set_defaults(handler=verify_bundle)

    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
