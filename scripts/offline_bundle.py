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
SOURCE_DIRECTORIES = (
    "modules",
    "dashboard",
    "citef-config",
    "shared",
    "orchestrator",
    "schemas",
)


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
    license_name = (
        metadata.get("License-Expression") or metadata.get("License") or UNKNOWN
    ).strip() or UNKNOWN
    owner = (
        metadata.get("Author") or metadata.get("Maintainer") or UNKNOWN
    ).strip() or UNKNOWN
    return {
        "name": metadata.get("Name", UNKNOWN),
        "version": metadata.get("Version", UNKNOWN),
        "source": source,
        "license": license_name,
        "owner": owner,
        "file": f"wheelhouse/{wheel.name}",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
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


def _write_lock_and_inventory(
    wheels: list[Path],
    wheelhouse: Path,
    destination_vm: str = "CTRL01",
    bundle_root: Path | None = None,
) -> list[dict]:
    by_name: dict[str, tuple[dict, str]] = {}
    for wheel in sorted(wheels):
        artifact = _wheel_inventory(wheel)
        if bundle_root is not None:
            artifact["file"] = (
                wheelhouse.relative_to(bundle_root) / wheel.name
            ).as_posix()
        normalized_name = re.sub(r"[-_.]+", "-", artifact["name"]).lower()
        prior = by_name.get(normalized_name)
        wheel_hash = _sha256(wheel)
        artifact.update(
            {
                "sha256": wheel_hash,
                "destination_vm": destination_vm,
                "offline_install_method": (
                    "Install from the bundled wheelhouse with pip --no-index, "
                    "--find-links, and --require-hashes."
                ),
            }
        )
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


def _copy_source_directories(
    bundle: Path, revision: str = "UNKNOWN (not a release build)", destination_vm: str = "CTRL01"
) -> list[dict[str, str]]:
    source_root = bundle / "source"
    source_root.mkdir(parents=True)
    copied = []
    for name in SOURCE_DIRECTORIES:
        source = REPO_ROOT / name
        if not source.is_dir():
            raise FileNotFoundError(f"required source directory is missing: {name}")
        destination = source_root / name
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        copied.append(
            {
                "name": name,
                "version": revision,
                "source": "https://github.com/Netstrike-development-team/NetStrike_Capstone_17",
                "license": "UNKNOWN (repository license/provenance review required)",
                "owner": "Netstrike-development-team",
                "sha256": _directory_sha256(destination),
                "destination_vm": destination_vm,
                "offline_install_method": (
                    "Copy the bundled source tree into the matching immutable application release; "
                    "no package-manager or network fetch is required."
                ),
                "path": destination.relative_to(bundle).as_posix(),
            }
        )
    return copied


def _runtime_inventory(
    runtime_archive: Path, source: str, version: str, destination_vm: str
) -> dict[str, str]:
    return {
        "name": "CPython portable runtime",
        "version": version,
        "source": source,
        "license": "Python Software Foundation License; review the upstream distribution terms",
        "owner": "Astral Software (python-build-standalone)",
        "sha256": _sha256(runtime_archive),
        "destination_vm": destination_vm,
        "offline_install_method": (
            "Extract the bundled runtime archive into the deployment's runtime directory; "
            "no network access is required."
        ),
        "file": runtime_archive.relative_to(runtime_archive.parents[1]).as_posix(),
    }


def _copy_ansible_collection_archives(
    archives: list[str], bundle: Path, destination_vm: str = "CTRL01"
) -> list[dict]:
    collection_dir = bundle / "ansible" / "collections"
    collection_dir.mkdir(parents=True)
    inventory = []
    names = set()
    for archive_name in archives:
        source = Path(archive_name).resolve()
        if not source.is_file() or source.suffixes[-2:] != [".tar", ".gz"]:
            raise ValueError(f"Ansible collection must be a .tar.gz archive: {archive_name}")

        with tarfile.open(source, "r:gz") as archive:
            manifests = [
                member for member in archive.getmembers()
                if PurePosixPath(member.name).name == "MANIFEST.json" and member.isfile()
            ]
            if len(manifests) != 1:
                raise ValueError(f"expected one MANIFEST.json in Ansible collection {source.name}")
            manifest_file = archive.extractfile(manifests[0])
            if manifest_file is None:
                raise ValueError(f"unable to read Ansible collection manifest: {source.name}")
            manifest = json.load(manifest_file)

        collection = manifest.get("collection_info", {})
        namespace = collection.get("namespace")
        collection_name = collection.get("name")
        version = collection.get("version")
        if not all(isinstance(value, str) and value for value in (namespace, collection_name, version)):
            raise ValueError(f"invalid Ansible collection identity in {source.name}")
        identity = f"{namespace}.{collection_name}".lower()
        if identity in names:
            raise ValueError(f"duplicate Ansible collection: {identity}")
        names.add(identity)

        destination = collection_dir / source.name
        shutil.copyfile(source, destination)
        licenses = collection.get("license", [])
        if isinstance(licenses, str):
            licenses = [licenses]
        if not isinstance(licenses, list) or not all(
            isinstance(license_name, str) for license_name in licenses
        ):
            licenses = []
        licenses = [license_name.strip() for license_name in licenses if license_name.strip()]
        authors = collection.get("authors", [])
        owner = (
            ", ".join(author.strip() for author in authors if author.strip())
            if isinstance(authors, list) and all(isinstance(author, str) for author in authors)
            else UNKNOWN
        )
        inventory.append(
            {
                "name": identity,
                "version": version,
                "source": "Ansible Galaxy",
                "license": ", ".join(licenses) or UNKNOWN,
                "owner": owner or UNKNOWN,
                "sha256": _sha256(destination),
                "destination_vm": destination_vm,
                "offline_install_method": (
                    "Install the bundled collection archive with ansible-galaxy collection "
                    "install --offline and a local collections path."
                ),
                "file": destination.relative_to(bundle).as_posix(),
            }
        )
    if not inventory:
        raise ValueError("no Ansible collection archives were provided")
    return sorted(inventory, key=lambda item: item["name"].lower())


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
        artifacts = _write_lock_and_inventory(wheels, wheelhouse, destination, bundle)
        source_artifacts = _copy_source_directories(bundle, revision, destination)
        ansible_collections = _copy_ansible_collection_archives(
            args.ansible_collection_archive, bundle, destination
        )

        manifest = {
            "repository_revision": revision,
            "destination_vm": destination,
            "python_runtime": _runtime_inventory(
                bundled_runtime,
                runtime_url or "Source URL not provided",
                runtime_version,
                destination,
            ),
            "requirements_inputs": [
                path.relative_to(REPO_ROOT).as_posix() for path in requirement_files
            ],
            "artifacts": artifacts,
            "source_artifacts": source_artifacts,
            "ansible_collections": ansible_collections,
        }
        (bundle / "inventory.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _write_checksums(bundle)
        with tarfile.open(output, "w:gz") as archive:
            archive.add(bundle, arcname=bundle.name)

    print(
        f"Created {output} with {len(artifacts)} Python packages, "
        f"{len(source_artifacts)} source trees, and {len(ansible_collections)} "
        f"Ansible collections for {destination}."
    )


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


def _verify_inventory_artifacts(bundle: Path, inventory: dict) -> None:
    destination = _validate_destination(inventory["destination_vm"])
    artifacts = [inventory["python_runtime"]]
    artifacts.extend(inventory.get("artifacts", []))
    artifacts.extend(inventory.get("source_artifacts", []))
    artifacts.extend(inventory.get("ansible_collections", []))
    required_fields = (
        "name",
        "version",
        "source",
        "license",
        "owner",
        "sha256",
        "destination_vm",
        "offline_install_method",
    )
    for artifact in artifacts:
        for field in required_fields:
            if not isinstance(artifact.get(field), str) or not artifact[field].strip():
                raise ValueError(f"offline inventory has a missing {field} field")
        if artifact["destination_vm"] != destination:
            raise ValueError(f"offline inventory destination mismatch: {artifact['name']}")
        if not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
            raise ValueError(f"invalid inventory SHA-256: {artifact['name']}")

        path_field = "path" if "path" in artifact else "file"
        if not isinstance(artifact.get(path_field), str) or not artifact[path_field]:
            raise ValueError(f"offline inventory has no {path_field}: {artifact['name']}")
        relative_path = _safe_relative_path(artifact[path_field])
        path = bundle.joinpath(*relative_path.parts)
        if path_field == "path":
            if not path.is_dir():
                raise ValueError(f"missing inventory source tree: {artifact['name']}")
            actual_hash = _directory_sha256(path)
        else:
            if not path.is_file():
                raise ValueError(f"missing inventory file: {artifact['name']}")
            actual_hash = _sha256(path)
        if actual_hash != artifact["sha256"]:
            raise ValueError(f"inventory SHA-256 mismatch: {artifact['name']}")


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
        _verify_inventory_artifacts(bundle, inventory)
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

        source_artifacts = inventory.get("source_artifacts", [])
        source_names = {artifact["name"] for artifact in source_artifacts}
        if source_names != set(SOURCE_DIRECTORIES):
            raise ValueError("bundle is missing required module, dashboard, or Ansible source")
        for artifact in source_artifacts:
            source_path = _safe_relative_path(artifact["path"])
            if source_path.parts[0] != "source" or not bundle.joinpath(*source_path.parts).is_dir():
                raise ValueError(f"missing bundled source directory: {artifact['path']}")

        collection_archives = []
        for collection in inventory.get("ansible_collections", []):
            collection_path = _safe_relative_path(collection["file"])
            if collection_path.parts[:2] != ("ansible", "collections"):
                raise ValueError(f"invalid Ansible collection path: {collection['file']}")
            collection_archive = bundle.joinpath(*collection_path.parts)
            if not collection_archive.is_file():
                raise ValueError(f"missing Ansible collection archive: {collection['file']}")
            collection_archives.append(str(collection_archive))
        if not collection_archives:
            raise ValueError("bundle contains no Ansible collection archives")

        ansible_galaxy = python.parent / "ansible-galaxy"
        collection_install = [
            str(ansible_galaxy),
            "collection",
            "install",
            "--offline",
            "--collections-path",
            str(Path(temporary) / "ansible-collections"),
            *collection_archives,
        ]
        subprocess.run(collection_install, check=True, env=env)

    print(
        f"Checksums, source files, Python {runtime_version}, offline dependency "
        f"installation, and Ansible collections are valid for {destination}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build", help="package runtime, dependencies, project source, and Ansible collections"
    )
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
    build.add_argument(
        "--ansible-collection-archive",
        action="append",
        required=True,
        help="Ansible Galaxy collection .tar.gz archive (repeat for each collection)",
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
