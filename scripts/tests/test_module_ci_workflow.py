"""Execute the real workflow shell offline and verify CI evidence contracts."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
PINS = {
    "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/setup-node": "249970729cb0ef3589644e2896645e5dc5ba9c38",
    "actions/upload-artifact": "b7c566a772e6b6bfb58ed0dc250532a479d7789f",
}
MODULES = [
    "modules/01-osint-profiler", "modules/02-phishing-infra", "modules/03-vishing-scripts",
    "modules/04-mfa-fatigue-sim", "modules/05-lateral-movement", "modules/06-cloud-exfil",
    "modules/07-ransomware-sim", "orchestrator", "dashboard", "detection",
]


def workflow(name="backend-ci.yml"):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def step(name):
    return next(item for item in workflow()["jobs"]["module-checks"]["steps"]
                if item.get("name") == name)


INSPECT = "Inspect module tests and report destination"
RUN = "Run module tests and preserve coverage (strict)"


def detect(tmp_path, module, *, tests=True):
    directory = tmp_path / module
    directory.mkdir(parents=True)
    if tests:
        (directory / "tests").mkdir()
    output = tmp_path / "outputs.txt"
    environment = os.environ | {
        "MODULE_PATH": module, "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path / "runner temp"),
    }
    result = subprocess.run(["bash", "-c", step(INSPECT)["run"]], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return directory, fields, environment, result


FAKE_PYTHON = '''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["CALL_LOG"]).open("a") as output:
    output.write(json.dumps({"args": args, "cwd": str(Path.cwd()),
                             "coverage": os.environ["COVERAGE_FILE"]}) + "\\n")
if args[:2] != ["-m", "coverage"]:
    raise SystemExit(99)
command = args[2]
if command == "run":
    Path(os.environ["COVERAGE_FILE"]).write_text("synthetic coverage fixture")
    raise SystemExit(int(os.environ["TEST_EXIT"]))
if command == "report":
    print("synthetic text coverage fixture")
    raise SystemExit(int(os.environ["REPORT_EXIT"]))
if command == "html":
    destination = Path(args[-1])
    destination.mkdir(parents=True)
    (destination / "index.html").write_text("synthetic html coverage fixture")
    raise SystemExit(int(os.environ["HTML_EXIT"]))
raise SystemExit(99)
'''


@pytest.mark.parametrize("test_status,report_status,html_status,expected", [
    (0, 0, 0, 0), (1, 0, 0, 1), (2, 0, 0, 2), (5, 0, 0, 5),
    (0, 3, 0, 3), (0, 0, 4, 4), (1, 3, 4, 1), (0, 3, 4, 3),
])
def test_shell_preserves_test_and_reporting_failures_and_available_evidence(
    tmp_path, test_status, report_status, html_status, expected,
):
    directory, fields, environment, _result = detect(tmp_path, "modules/example")
    tools = tmp_path / "tools"
    tools.mkdir()
    fake = tools / "python"
    fake.write_text(f"#!{sys.executable}\n" + FAKE_PYTHON)
    fake.chmod(0o700)
    log = tmp_path / "calls.jsonl"
    environment |= {
        "PATH": str(tools) + os.pathsep + environment["PATH"],
        "REPORT_ROOT": fields["report_root"], "CALL_LOG": str(log),
        "TEST_EXIT": str(test_status), "REPORT_EXIT": str(report_status),
        "HTML_EXIT": str(html_status),
    }
    result = subprocess.run(["bash", "-c", step(RUN)["run"]], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == expected, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [call["args"][2] for call in calls] == ["run", "report", "html"]
    assert calls[0]["args"] == ["-m", "coverage", "run", "-m", "pytest", "tests/", "-v"]
    report_root = Path(fields["report_root"])
    assert all(Path(call["cwd"]) == directory for call in calls)
    assert all(call["coverage"] == str(report_root / ".coverage") for call in calls)
    assert (report_root / "coverage.txt").is_file()
    assert (report_root / "html/index.html").is_file()
    assert not (tmp_path / "modules/coverage.txt").exists()


@pytest.mark.parametrize("module", ["modules/example", "dashboard", "module with spaces"])
@pytest.mark.parametrize("tests", [True, False])
def test_detection_uses_absolute_quoted_destinations_and_explicit_no_test_boundary(tmp_path, module, tests):
    _directory, fields, _environment, result = detect(tmp_path, module, tests=tests)
    assert fields["has_tests"] == str(tests).lower()
    assert fields["name"] == Path(module).name and "/" not in fields["name"]
    assert fields["report_root"] == str(tmp_path / "runner temp/module-coverage" / Path(module).name)
    assert not Path(fields["report_root"]).exists()  # Inspection only.
    if not tests:
        assert "no test-validation or coverage claim" in result.stdout


@pytest.mark.parametrize("passes", [True, False])
def test_real_coverage_and_pytest_write_uploadable_reports_on_success_and_failure(tmp_path, passes):
    directory, fields, environment, _result = detect(tmp_path, "modules/example")
    (directory / "tests/test_example.py").write_text(f"def test_example():\n    assert {passes!r}\n")
    environment |= {
        "REPORT_ROOT": fields["report_root"],
        "PATH": str(Path(sys.executable).parent) + os.pathsep + environment["PATH"],
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    result = subprocess.run(["bash", "-c", step(RUN)["run"]], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == (0 if passes else 1), result.stdout + result.stderr
    assert (Path(fields["report_root"]) / "coverage.txt").stat().st_size > 0
    assert (Path(fields["report_root"]) / "html/index.html").stat().st_size > 0


def test_matrix_jobs_are_stable_bounded_and_fail_independently():
    data = workflow()
    assert set(data["jobs"]) == {"event-contract", "module-checks"}
    jobs = data["jobs"]
    strategy = jobs["module-checks"]["strategy"]
    assert strategy["matrix"]["module"] == MODULES
    assert strategy["fail-fast"] is False and strategy["max-parallel"] == 3
    assert jobs["module-checks"]["timeout-minutes"] == 15
    assert jobs["event-contract"]["timeout-minutes"] == 5
    # PyYAML's YAML 1.1 loader treats unquoted `on` as boolean True.
    events = data.get("on", data.get(True))
    assert events == {"push": {"branches": ["main", "dev"]},
                      "pull_request": {"branches": ["main", "dev"]}}
    for item in jobs["module-checks"]["steps"]:
        if item.get("continue-on-error"):
            assert item["name"] == "Lint module"  # Lint remains informational.
    assert "|| true" not in step(RUN)["run"]
    assert "continue-on-error" not in step(RUN)
    assert step(RUN)["if"] == "steps.module-tests.outputs.has_tests == 'true'"


def test_reports_upload_on_failure_only_for_tested_modules_without_slashes():
    for name, suffix, kind in (("Upload txt coverage report", "coverage.txt", "txt"),
                               ("Upload HTML coverage report", "html/", "html")):
        item = step(name)
        assert item["if"] == "always() && steps.module-tests.outputs.has_tests == 'true'"
        assert item["with"]["path"] == "${{ steps.module-tests.outputs.report_root }}/" + suffix
        assert item["with"]["name"] == f"coverage-{kind}-${{{{ steps.module-tests.outputs.name }}}}"
        assert "matrix.module" not in item["with"]["name"]
        assert item["with"]["if-no-files-found"] == "error"
        assert item["with"]["retention-days"] == 14


@pytest.mark.parametrize("name", ["backend-ci.yml", "backend-security-ci.yml",
                                 "local-rehearsal-ci.yml", "offline-bundle.yml"])
def test_official_node24_pins_permissions_runner_and_runtime_contracts(name):
    data = workflow(name)
    assert data["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in data.get("on", data.get(True))
    for job in data["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] > 0
        for item in job["steps"]:
            if "uses" not in item:
                continue
            action, revision = item["uses"].split("@")
            assert revision == PINS[action]
            if action == "actions/checkout":
                assert item["with"]["persist-credentials"] is False
            if action == "actions/setup-node":
                assert item["with"]["node-version"] == "22"
                assert item["with"]["package-manager-cache"] is False
            if action == "actions/setup-python" and name != "offline-bundle.yml":
                assert item["with"]["python-version"] == "3.11"
    if name == "offline-bundle.yml":
        assert data["env"] == {"DESTINATION": "CTRL01", "PYTHON_VERSION": "3.11.16",
                               "PYTHON_BUILD": "20260924"}
        assert data.get("on", data.get(True)) == {"workflow_dispatch": None}
