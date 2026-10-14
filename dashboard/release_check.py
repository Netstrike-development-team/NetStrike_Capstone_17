"""Read-only selected-bundle source consistency, not runtime or range acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SOURCE_TREES = ("modules", "dashboard", "citef-config", "shared", "orchestrator", "schemas")
MAX_INVENTORY_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TREE_BYTES = 128 * 1024 * 1024
MAX_TREE_ENTRIES = 10_000
MAX_DEPTH = 32
NOT_CHECKED = [
    "source_authenticity_or_review_approval", "running_process_or_loaded_bytecode",
    "whole_bundle_archive_digest", "runtime_wheels_locks_and_collections",
    "installer_hashes_and_licenses", "configuration_or_application_readiness",
    "vm_splunk_network_and_snapshots", "participant_usability_and_client_acceptance",
]


def _hex(value, size):
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
        raise ValueError("invalid identity")
    return value


def _same(value, expected):
    if value != expected:
        raise ValueError("identity mismatch")
    return value


def _directory(path):
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError("not a real directory")
    return path


def _read_regular(path, maximum):
    """Do not follow final links or block on special files; bound memory and reads."""
    expected = path.lstat()
    if (not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1
            or expected.st_size > maximum):
        raise ValueError("unsafe or oversized file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > maximum
                or any(getattr(expected, field) != getattr(before, field) for field in fields)):
            raise ValueError("unsafe or oversized file")
        content = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())
        if (len(content) > maximum or len(content) != before.st_size
                or any(getattr(before, field) != getattr(after, field) for field in fields)):
            raise ValueError("file changed or exceeded limit")
        return content


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata")
        result[key] = value
    return result


def _metadata(content):
    inventory = json.loads(content, object_pairs_hook=_unique)
    revision = _hex(inventory["repository_revision"], 40)
    destination = inventory["destination_vm"]
    if not isinstance(destination, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", destination):
        raise ValueError("invalid destination")
    artifacts = inventory["source_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != len(SOURCE_TREES):
        raise ValueError("incomplete source inventory")
    entries = {}
    for entry in artifacts:
        name = entry["name"]
        if (name not in SOURCE_TREES or name in entries
                or entry["path"] != f"source/{name}" or entry["version"] != revision
                or entry["destination_vm"] != destination):
            raise ValueError("invalid source record")
        entries[name] = _hex(entry["sha256"], 64)
    return revision, entries


def _tree_hash(root):
    """Independently reproduce the existing offline builder's path/NUL/hash format."""
    _directory(root)
    paths, total_entries, pending = [], 0, [(root, 0)]
    while pending:
        parent, depth = pending.pop()
        _directory(parent)
        with os.scandir(parent) as entries:
            for entry in entries:
                total_entries += 1
                if total_entries > MAX_TREE_ENTRIES or entry.is_symlink():
                    raise ValueError("unsafe or oversized source tree")
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_DEPTH:
                        raise ValueError("source tree exceeds depth limit")
                    pending.append((Path(entry.path), depth + 1))
                else:
                    paths.append(Path(entry.path))
    digest, total_bytes = hashlib.sha256(), 0
    # Path sorting deliberately matches the builder (not string-path sorting).
    for path in sorted(paths):
        content = _read_regular(path, min(MAX_FILE_BYTES, MAX_TREE_BYTES - total_bytes))
        total_bytes += len(content)
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _source_root(root):
    path = _directory(root / "source")
    names = set()
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name not in SOURCE_TREES or entry.name in names:
                raise ValueError("unexpected source root entries")
            names.add(entry.name)
    if names != set(SOURCE_TREES):
        raise ValueError("unexpected source root entries")
    return path


def inspect_release(bundle_root, *, expected_revision, expected_inventory_sha256):
    """Inspect only selected extracted source; do not import or execute that source."""
    report = {
        "schema_version": "1.0.0", "scope": "selected_application_source_only",
        "read_only": True, "source_verified": False, "repository_revision": None,
        "inventory_sha256": None, "source_artifacts": [], "checks": [], "blockers": [],
        "source_authenticity_verified": False, "running_process_verified": False,
        "external_readiness_verified": False, "not_checked": list(NOT_CHECKED),
    }

    def probe(name, operation):
        try:
            result = operation()
        except Exception:  # pylint: disable=broad-exception-caught
            # Safe boundary: never echo paths or arbitrary metadata/exception text.
            report["checks"].append({"check_id": name, "passed": False, "code": "invalid_or_unavailable"})
            report["blockers"].append(name)
            return None
        report["checks"].append({"check_id": name, "passed": True, "code": "matched"})
        return result

    if probe("expected_release_identity", lambda: (
        _hex(expected_revision, 40), _hex(expected_inventory_sha256, 64)
    )) is None:
        return report

    def root_and_inventory():
        root = _directory(Path(bundle_root)).resolve(strict=True)
        content = _read_regular(root / "inventory.json", MAX_INVENTORY_BYTES)
        report["inventory_sha256"] = hashlib.sha256(content).hexdigest()
        if report["inventory_sha256"] != expected_inventory_sha256:
            raise ValueError("inventory does not match expected digest")
        return root, content

    inspected = probe("inventory_digest", root_and_inventory)
    if inspected is None:
        return report
    root, content = inspected
    metadata = probe("source_inventory", lambda: _metadata(content))
    if metadata is None:
        return report
    revision, entries = metadata
    report["repository_revision"] = revision

    probe("expected_repository_revision", lambda: _same(revision, expected_revision))
    source = probe("source_root", lambda: _source_root(root))
    if source is None:
        return report
    for name in SOURCE_TREES:
        digest = probe(f"source_{name}", lambda name=name: _same(_tree_hash(source / name), entries[name]))
        if digest is not None:
            report["source_artifacts"].append({"name": name, "sha256": digest})
    report["source_verified"] = not report["blockers"]
    return report


class SafeParser(argparse.ArgumentParser):
    """Invalid arguments must not echo private paths or accidentally pasted secrets."""

    def error(self, _message):
        self.exit(2, "Invalid release-check arguments. Use --help.\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--expect-revision", required=True)
    parser.add_argument("--expect-inventory-sha256", required=True)
    arguments = parser.parse_args(argv)
    report = inspect_release(
        arguments.bundle_root, expected_revision=arguments.expect_revision,
        expected_inventory_sha256=arguments.expect_inventory_sha256,
    )
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["source_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
