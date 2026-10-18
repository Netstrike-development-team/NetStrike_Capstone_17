"""Inert defaults, observed kernel boundary, bounded commands and no fallback."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile

import pytest
import yaml

from scripts import offline_smoke as smoke

ROOT = Path(__file__).resolve().parents[2]


def archive(tmp_path):
    path = tmp_path / "bundle.tar.gz"
    with tarfile.open(path, "w:gz") as handle:
        member = tarfile.TarInfo("netstrike-offline-bundle/example")
        member.size = 2
        handle.addfile(member, io.BytesIO(b"ok"))
    return path


def test_preview_has_no_reads_writes_or_execution(tmp_path, monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview performed work")
    monkeypatch.setattr(smoke, "execute", forbidden)
    monkeypatch.setattr(smoke, "isolation", forbidden)
    assert smoke.main(["--archive", "PRIVATE", "--output", str(tmp_path / "new")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["writes_performed"] and not list(tmp_path.iterdir())


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    monkeypatch.setattr(smoke.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(smoke.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(smoke.os, "readlink", lambda _path: "net:[200]")
    monkeypatch.setattr(smoke.socket, "if_nameindex", lambda: [(1, "lo")])
    files = {"/proc/self/status": "NoNewPrivs:\t1\n" + "".join(name + ":\t0000\n" for name in ("CapEff", "CapPrm", "CapBnd", "CapAmb", "CapInh")),
             "/proc/net/route": "Iface Destination\n", "/proc/net/ipv6_route": ""}
    original_read, original_exists = Path.read_text, Path.exists
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw: files[str(path)] if str(path) in files else original_read(path, *a, **kw))
    monkeypatch.setattr(Path, "exists", lambda path: str(path) in files or original_exists(path))
    return files


def test_boundary_records_actual_namespace_and_interfaces(boundary):
    observed = smoke.isolation("net:[100]")
    assert observed["isolated_namespace"] == "net:[200]"
    assert observed["host_namespace"] == "net:[100]"
    assert observed["outbound_network_unavailable"]


@pytest.mark.parametrize("change", ["platform", "architecture", "root", "nnp", "caps", "namespace", "interface", "route", "ipv6"])
def test_boundary_refuses_unsafe_execution(boundary, monkeypatch, change):
    if change == "platform":
        monkeypatch.setattr(smoke.sys, "platform", "darwin")
    elif change == "architecture":
        monkeypatch.setattr(smoke.platform, "machine", lambda: "aarch64")
    elif change == "root":
        monkeypatch.setattr(smoke.os, "geteuid", lambda: 0)
    elif change == "nnp":
        boundary["/proc/self/status"] = boundary["/proc/self/status"].replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")
    elif change == "caps":
        boundary["/proc/self/status"] = boundary["/proc/self/status"].replace("CapBnd:\t0000", "CapBnd:\t0001")
    elif change == "namespace":
        monkeypatch.setattr(smoke.os, "readlink", lambda _path: "net:[100]")
    elif change == "interface":
        monkeypatch.setattr(smoke.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    elif change == "route":
        boundary["/proc/net/route"] += "eth0 00000000\n"
    else:
        boundary["/proc/net/ipv6_route"] = "000000000 eth0\n"
    with pytest.raises(ValueError):
        smoke.isolation("net:[100]")


@pytest.mark.parametrize("failure", ["digest", "revision", "existing", "symlink", "limit"])
def test_preflight_refusal_preserves_output(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(smoke, "isolation", lambda _host: {"isolated": True})
    source, output = archive(tmp_path), tmp_path / "new"
    digest, revision = hashlib.sha256(source.read_bytes()).hexdigest(), "a" * 40
    if failure == "digest":
        digest = "0" * 64
    elif failure == "revision":
        revision = "PRIVATE"
    elif failure == "existing":
        output.mkdir()
        (output / "keep").write_text("unchanged")
    elif failure == "symlink":
        link = tmp_path / "linked"
        link.symlink_to(source)
        source = link
    else:
        monkeypatch.setattr(smoke, "MAX_EXPANDED", 1)
    with pytest.raises(ValueError):
        smoke.execute(source, output, revision=revision, archive_sha256=digest, host_namespace="net:[100]")
    assert not output.exists() or (output / "keep").read_text() == "unchanged"


def test_command_preserves_bounded_diagnostics_and_exit_status(tmp_path):
    log = tmp_path / "command.log"
    smoke.command([sys.executable, "-I", "-c", "print('synthetic')"], cwd=tmp_path, env={"PATH": os.defpath}, log=log)
    assert log.read_text().strip() == "synthetic"
    with pytest.raises(ValueError, match="child_command_failed"):
        smoke.command([sys.executable, "-I", "-c", "raise SystemExit(3)"], cwd=tmp_path, env={}, log=tmp_path / "failed.log")


@pytest.mark.parametrize("kind", ["timeout", "volume"])
def test_command_kills_timed_out_or_excess_output(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(smoke, "MAX_LOG", 1024)
    code = "import time; time.sleep(10)" if kind == "timeout" else "print('x'*100000)"
    log = tmp_path / "child.log"
    with pytest.raises(ValueError):
        smoke.command([sys.executable, "-I", "-c", code], cwd=tmp_path, env={}, log=log, timeout=0.1 if kind == "timeout" else 5)
    assert log.stat().st_size <= 1024


def test_cli_error_does_not_echo_private_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(smoke, "execute", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("PRIVATE")))
    assert smoke.main(["--execute", "--archive", "PRIVATE", "--output", str(tmp_path), "--expect-revision", "a" * 40,
        "--expect-archive-sha256", "0" * 64, "--host-network-namespace", "net:[100]"]) == 1
    assert "PRIVATE" not in capsys.readouterr().err


def test_workflow_uses_actual_archive_and_kernel_boundary_without_bypasses():
    workflow = yaml.safe_load((ROOT / ".github/workflows/offline-bundle.yml").read_text())
    steps = workflow["jobs"]["build"]["steps"]
    step = next(s for s in steps if s["name"] == "Smoke full play from the actual bundle with kernel networking isolated")
    command = step["run"]
    for expected in ("unshare --net", "ip link set lo up", "--bounding-set=-all", "--no-new-privs", "--clear-groups",
                     "--archive", "--expect-revision", "--expect-archive-sha256", "--host-network-namespace", "--execute"):
        assert expected in command
    assert not step.get("continue-on-error") and "|| true" not in command
    upload = next(s for s in steps if s["name"].startswith("Retain bounded synthetic"))
    assert upload["if"] == "always()"
    assert "portal.sqlite3" not in upload["with"]["path"]
    assert "offline-fullplay-smoke/**" not in upload["with"]["path"]


@pytest.mark.parametrize("failure", [None, "install", "worker", "receipt"])
def test_orchestration_uses_only_bundled_runtime_and_dependency_sources(tmp_path, monkeypatch, failure):
    source = archive(tmp_path)
    fake = tmp_path / "fixture-bundle"
    (fake / "runtime").mkdir(parents=True)
    (fake / "runtime/python-runtime.tar.gz").write_bytes(source.read_bytes())
    inventory = {"repository_revision": "a" * 40, "destination_vm": "CTRL01",
        "source_artifacts": [{"name": name} for name in smoke.bundle_tools.SOURCE_DIRECTORIES],
        "python_runtime": {"file": "runtime/python-runtime.tar.gz", "version": "3.11.16"},
        "ansible_collections": [{"file": "ansible/collections/example.tar.gz"}]}
    (fake / "inventory.json").write_text(json.dumps(inventory))
    monkeypatch.setattr(smoke, "isolation", lambda _host: {"interfaces": ["lo"]})
    monkeypatch.setattr(smoke.bundle_tools, "_extract_bundle", lambda *_a: fake)
    checked = []
    monkeypatch.setattr(smoke.bundle_tools, "_verify_checksums", lambda root: checked.append(root))
    monkeypatch.setattr(smoke.bundle_tools, "_verify_inventory_artifacts", lambda *_a: None)
    python = tmp_path / "output/runtime/python/bin/python3.11"
    monkeypatch.setattr(smoke.bundle_tools, "_extract_python_runtime", lambda *_a: (python, "3.11.16"))
    calls = []

    def command(argv, **options):
        calls.append((argv, options))
        if failure == "install" and len(calls) == 1 or failure == "worker" and len(calls) == 3:
            raise ValueError("synthetic command failure")
        if len(calls) == 3:
            report = {"passed": failure != "receipt", "source_revision": "a" * 40,
                "external_readiness_verified": False, "splunk_ingestion_verified": False,
                "packaged_runtime_verified": True, "application_reset_verified": True,
                "archive_preserved": True, "publication_retry_verified": True}
            (tmp_path / "output/application-smoke.json").write_text(json.dumps(report))

    monkeypatch.setattr(smoke, "command", command)
    monkeypatch.setenv("PYTHONPATH", "PRIVATE-CHECKOUT")
    monkeypatch.setenv("HTTPS_PROXY", "PRIVATE-PROXY")
    options = dict(revision="a" * 40, archive_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), host_namespace="net:[100]")
    if failure:
        with pytest.raises(ValueError):
            smoke.execute(source, tmp_path / "output", **options)
    else:
        assert smoke.execute(source, tmp_path / "output", **options)["passed"]
        assert len(checked) == 2 and len(calls) == 3
        assert calls[2][0][0] == str(python)
        assert calls[2][0][1:3] == ["-I", "-B"]
        assert str(fake / "source") in calls[2][0]
        assert "--offline" in calls[1][0]
    pip, options = calls[0]
    for flag in ("--no-index", "--require-hashes", "--isolated", "--no-cache-dir"):
        assert flag in pip
    assert str(fake / "destinations/CTRL01/wheelhouse") in pip
    assert "PYTHONPATH" not in options["env"] and "HTTPS_PROXY" not in options["env"]
    assert options["cwd"] == tmp_path / "output"
    result = json.loads((tmp_path / "output/smoke-summary.json").read_text())
    assert result["passed"] == (failure is None)
    assert "PRIVATE" not in json.dumps(result)
