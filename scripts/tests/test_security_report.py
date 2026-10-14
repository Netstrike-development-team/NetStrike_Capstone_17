"""Scanner finding/error propagation and report retention contracts."""

import json
from pathlib import Path
import re

import pytest

from scripts import check_security_report


def clean_report():
    return {"errors": [], "results": [], "metrics": {"_totals": {"loc": 42}}}


def write_report(tmp_path, value):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    return path


def test_success_is_read_only_and_cli_returns_zero(tmp_path, capsys):
    path = write_report(tmp_path, clean_report())
    before = path.read_bytes()
    assert check_security_report.report_passed(path)
    assert check_security_report.main([str(path)]) == 0
    assert capsys.readouterr().out == "Security report passed.\n"
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [
    "finding", "parse-error", "missing-errors", "missing-results", "missing-metrics",
    "missing-totals", "missing-loc", "zero-loc", "negative-loc", "string-loc",
    "bool-loc", "null-results", "object-errors",
])
def test_findings_scan_errors_and_incomplete_reports_fail_closed(tmp_path, change, capsys):
    value = clean_report()
    if change == "finding":
        value["results"] = [{"issue_severity": "MEDIUM", "code": "private-report-prose"}]
    elif change == "parse-error":
        value["errors"] = [{"filename": "private-report-prose", "reason": "SyntaxError"}]
    elif change.startswith("missing-"):
        key = change.removeprefix("missing-")
        container = value["metrics"]["_totals"] if key == "loc" else value["metrics"] if key == "totals" else value
        container.pop("_totals" if key == "totals" else key)
    elif change.endswith("-loc"):
        value["metrics"]["_totals"]["loc"] = {"zero-loc": 0, "negative-loc": -1,
                                               "string-loc": "42", "bool-loc": True}[change]
    elif change == "null-results":
        value["results"] = None
    else:
        value["errors"] = {}
    path = write_report(tmp_path, value)
    assert not check_security_report.report_passed(path)
    assert check_security_report.main([str(path)]) == 1
    assert "private-report-prose" not in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["not-json", "[]", "null", '{"errors": [], "errors": [1]}'])
def test_malformed_and_duplicate_report_data_is_rejected(tmp_path, raw):
    path = tmp_path / "report.json"
    path.write_text(raw)
    assert not check_security_report.report_passed(path)


def test_missing_unreadable_or_oversized_report_is_rejected(tmp_path, monkeypatch):
    assert not check_security_report.report_passed(tmp_path / "missing")
    assert not check_security_report.report_passed(tmp_path)
    path = write_report(tmp_path, clean_report())
    monkeypatch.setattr(check_security_report, "MAX_REPORT_BYTES", 8)
    assert not check_security_report.report_passed(path)


def test_cli_error_does_not_echo_unknown_values(capsys):
    with pytest.raises(SystemExit) as error:
        check_security_report.main(["--unknown", "private-report-prose"])
    assert error.value.code == 2
    assert "private-report-prose" not in capsys.readouterr().err


def test_security_workflow_has_strict_coverage_and_preserves_failure_reports():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/backend-security-ci.yml").read_text()
    assert "  bandit:" in workflow and "contents: read" in workflow
    assert "timeout-minutes: 5" in workflow and "bandit==1.9.4" in workflow
    assert "if: always()" in workflow and "retention-days: 14" in workflow
    steps = workflow.split("      - name: ")
    legacy = next(step for step in steps if step.startswith("Legacy module"))
    assert "continue-on-error: true" in legacy
    strict = [step for step in steps if step.startswith("Strict maintained")]
    assert len(strict) == 2
    for step in strict:
        assert "set -e" in step
        assert "-ll -f json" in step and "check_security_report.py" in step
        assert "continue-on-error" not in step and "|| true" not in step
    assert "-r dashboard orchestrator shared scripts" in strict[0]
    assert "-x /tests/,/__pycache__/" in strict[0]
    for path in (
        "modules/01-osint-profiler/exercise_profiles.py",
        "modules/04-mfa-fatigue-sim/identity_actions.py",
        "modules/05-lateral-movement/endpoint_actions.py",
        "modules/06-cloud-exfil/cloud_actions.py",
        "modules/07-ransomware-sim/impact_actions.py",
    ):
        assert path in strict[1] and (root / path).is_file()
    for event in ("push", "pull_request"):
        assert re.search(rf"  {event}:\n    branches:\n      - main\n      - dev", workflow)
    upload = next(step for step in steps if step.startswith("Upload bandit report"))
    for name in ("bandit_report.txt", "application-security.json", "adapter-security.json"):
        assert name in upload
