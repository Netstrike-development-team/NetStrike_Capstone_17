"""Explicit, kernel-offline smoke of the actual bundle; preview is inert."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import offline_bundle as bundle_tools  # pylint: disable=wrong-import-position

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_MEMBERS = 20000
MAX_LOG = 2 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise ValueError(code)


def isolation(host_namespace):
    """Observe kernel state, not a user-provided 'offline' environment flag."""
    require(sys.platform == "linux" and platform.machine() in {"x86_64", "amd64"}, "linux_amd64_required")
    require(os.geteuid() != 0, "unprivileged_execution_required")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    require(status.get("NoNewPrivs", "").strip() == "1", "no_new_privileges_required")
    require(all(int(status[name].strip(), 16) == 0 for name in ("CapEff", "CapPrm", "CapBnd", "CapAmb", "CapInh")), "capabilities_must_be_dropped")
    require(isinstance(host_namespace, str) and re.fullmatch(r"net:\[[0-9]+\]", host_namespace), "host_namespace_reference_required")
    current_namespace = os.readlink("/proc/self/ns/net")
    require(current_namespace != host_namespace, "separate_network_namespace_required")
    require(socket.if_nameindex() == [(1, "lo")], "loopback_only_required")
    # Kernel routing tables must contain no non-loopback interface.
    routes = Path("/proc/net/route").read_text().splitlines()[1:]
    require(all(not line.split() or line.split()[0] == "lo" for line in routes), "external_route_present")
    ipv6 = Path("/proc/net/ipv6_route")
    if ipv6.exists():
        require(all(not line.split() or line.split()[-1] == "lo" for line in ipv6.read_text().splitlines()), "external_ipv6_route_present")
    return {"linux_amd64": True, "unprivileged": True, "no_new_privileges": True,
            "capabilities_dropped": True, "separate_network_namespace": True,
            "interfaces": ["lo"], "outbound_network_unavailable": True,
            "host_namespace": host_namespace, "isolated_namespace": current_namespace}


def inspect_archive(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_ARCHIVE, "unsafe_or_oversized_archive")
    total = count = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            count += 1
            total += member.size
            require(count <= MAX_MEMBERS and total <= MAX_EXPANDED and member.size <= MAX_ARCHIVE, "expanded_archive_limit")


def command(argv, *, cwd, env, log, timeout=180):
    """Bound diagnostics and terminate the exact child on timeout/failure."""
    with log.open("xb") as stream:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)  # nosec B603
        deadline = time.monotonic() + timeout
        completed, written = False, 0
        try:
            with process.stdout as pipe, selectors.DefaultSelector() as selector:
                selector.register(pipe, selectors.EVENT_READ)
                while True:
                    require(time.monotonic() < deadline, "child_timeout")
                    if not selector.select(timeout=0.05):
                        continue
                    chunk = os.read(pipe.fileno(), 65536)
                    if not chunk:
                        break
                    require(written + len(chunk) <= MAX_LOG, "diagnostic_limit")
                    stream.write(chunk)
                    written += len(chunk)
            require(process.wait(timeout=10) == 0, "child_command_failed")
            completed = True
        finally:
            if not completed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=10)


def execute(archive, output, *, revision, archive_sha256, host_namespace):
    boundary = isolation(host_namespace)  # Before output creation or runtime execution.
    require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "invalid_revision")
    require(isinstance(archive_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", archive_sha256), "invalid_digest")
    archive = Path(archive).absolute()
    inspect_archive(archive)
    require(bundle_tools._sha256(archive) == archive_sha256, "archive_digest_mismatch")
    supplied = Path(output).absolute()
    require(".." not in supplied.parts and supplied.name, "unsafe_output")
    output = supplied.parent.resolve(strict=True) / supplied.name
    require(not output.exists() and not output.is_symlink(), "new_output_required")
    output.mkdir(mode=0o700)
    stage = "extract_and_verify"
    report = {"scope": "offline_bundle_developer_smoke", "passed": False,
              "archive_sha256": archive_sha256, "repository_revision": revision,
              "external_readiness_verified": False, "splunk_ingestion_verified": False,
              "full_exercise_acceptance": False}
    try:
        (output / "network-boundary.json").write_text(json.dumps(boundary, indent=2) + "\n")
        bundle = bundle_tools._extract_bundle(archive, output / "bundle")
        bundle_tools._verify_checksums(bundle)
        inventory = json.loads((bundle / "inventory.json").read_text())
        bundle_tools._verify_inventory_artifacts(bundle, inventory)
        require(inventory["repository_revision"] == revision, "source_revision_mismatch")
        require({item["name"] for item in inventory["source_artifacts"]} == set(bundle_tools.SOURCE_DIRECTORIES), "source_inventory_incomplete")
        runtime_record = inventory["python_runtime"]
        runtime_path = bundle_tools._safe_relative_path(runtime_record["file"])
        require(runtime_path.parts[0] == "runtime", "invalid_runtime_path")
        runtime = bundle.joinpath(*runtime_path.parts)
        inspect_archive(runtime)
        python, version = bundle_tools._extract_python_runtime(runtime, output / "runtime", runtime_record["version"])
        destination = bundle_tools._validate_destination(inventory["destination_vm"])
        dependencies = bundle / "destinations" / destination
        env = {"PATH": os.defpath, "LANG": "C.UTF-8", "PIP_CONFIG_FILE": os.devnull,
               "PIP_NO_INDEX": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
               "ANSIBLE_CONFIG": str(output / "ansible.cfg"), "ANSIBLE_HOME": str(output / "ansible-home")}
        (output / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
        stage = "offline_dependency_install"
        command([str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
                 "--disable-pip-version-check", "--no-cache-dir", "--only-binary=:all:",
                 "--find-links", str(dependencies / "wheelhouse"), "--require-hashes",
                 "-r", str(dependencies / "requirements.lock")],
                cwd=output, env=env, log=output / "dependency-install.log")
        stage = "offline_collection_install"
        collections = []
        for item in inventory["ansible_collections"]:
            path = bundle_tools._safe_relative_path(item["file"])
            require(path.parts[:2] == ("ansible", "collections"), "invalid_collection_path")
            collections.append(str(bundle.joinpath(*path.parts)))
        require(collections, "collections_missing")
        command([str(python.parent / "ansible-galaxy"), "collection", "install", "--offline",
                 "--collections-path", str(output / "collections"), *collections],
                cwd=output, env=env, log=output / "collection-install.log")
        stage = "packaged_http_journey"
        source = bundle / "source"
        inventory_digest = bundle_tools._sha256(bundle / "inventory.json")
        bootstrap = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('dashboard.offline_smoke',run_name='__main__')"
        command([str(python), "-I", "-B", "-c", bootstrap, str(source), "--bundle", str(bundle),
                 "--output", str(output), "--revision", revision, "--inventory-sha256", inventory_digest],
                cwd=output, env=env, log=output / "application.log")
        application = json.loads((output / "application-smoke.json").read_text())
        require(application["passed"] and application["source_revision"] == revision
                and application["packaged_runtime_verified"]
                and application["application_reset_verified"] and application["archive_preserved"]
                and application["publication_retry_verified"]
                and not application["external_readiness_verified"] and not application["splunk_ingestion_verified"], "invalid_application_receipt")
        bundle_tools._verify_checksums(bundle)  # Packaged source must remain unchanged.
        require(isolation(host_namespace) == boundary, "isolation_changed")
        report.update(passed=True, stage="complete", python_version=version,
                      inventory_sha256=inventory_digest, network_boundary_verified=True,
                      application=application)
        return report
    finally:
        if not report["passed"]:
            report["failed_stage"] = stage
        (output / "smoke-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "Invalid offline smoke arguments. Use --help.\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-revision")
    parser.add_argument("--expect-archive-sha256")
    parser.add_argument("--host-network-namespace")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"scope": "offline_bundle_developer_smoke", "writes_performed": False,
                          "requires": ["Linux amd64", "separate loopback-only network namespace", "dropped capabilities", "reviewed actual bundle"],
                          "external_readiness_verified": False}))
        return 0
    if any(value is None for value in (args.archive, args.output, args.expect_revision, args.expect_archive_sha256, args.host_network_namespace)):
        parser.error("missing required execution input")
    try:
        result = execute(args.archive, args.output, revision=args.expect_revision,
                         archive_sha256=args.expect_archive_sha256, host_namespace=args.host_network_namespace)
    except Exception:
        print("Offline bundle smoke blocked or failed. Preserve private diagnostics; no range acceptance claimed.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
