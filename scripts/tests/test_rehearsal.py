"""Real full-play paths, failure guards, artifact tampering and inert CLI preview."""

from copy import deepcopy
import importlib
import json
import shutil
import socket
from pathlib import Path

import pytest

from scripts import rehearsal


@pytest.fixture(scope="module")
def full_package(tmp_path_factory):
    destination = tmp_path_factory.mktemp("rehearsal-parent") / "package"
    manifest = rehearsal.run_suite(destination)
    assert manifest["verified"], manifest
    return destination


def load_result(root, name):
    return json.loads((root / name / "result.json").read_text(encoding="utf-8"))


def copy_case(root, tmp_path, name="path-pass-pass-pass-pass"):
    destination = tmp_path / "copy"
    destination.mkdir()
    shutil.copytree(root / name, destination / name)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["cases"] = [item for item in manifest["cases"] if item["case_id"] == name]
    (destination / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return destination


def resign_file(root, name, content, case_name="path-pass-pass-pass-pass"):
    path = root / case_name / name
    path.write_text(content, encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cases"][0]["files_sha256"][name] = rehearsal._sha(path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_default_preview_does_not_start_services_write_or_query_git(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview attempted execution")

    monkeypatch.setattr(rehearsal, "Driver", forbidden)
    monkeypatch.setattr(rehearsal, "_source", forbidden)
    before = list(tmp_path.iterdir())
    assert rehearsal.main(["--output", str(tmp_path / "not-created")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["writes_performed"] is False
    assert len(output["cases"]) == 24
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("name", list(rehearsal.cases()))
def test_raw_telemetry_comparison_handles_each_real_rehearsal_export(
    full_package, tmp_path, name
):
    from dashboard.telemetry_check import compare, TelemetryCheckError

    expected = full_package / name / "events.jsonl"
    values = [json.loads(line) for line in expected.read_text().splitlines()]
    observed = tmp_path / "receiver-export.jsonl"
    observed.write_text("".join(json.dumps(value) + "\n" for value in reversed(values)))
    scope = {"exercise_id": values[0]["exercise_id"], "run_id": values[0]["run_id"]}
    matched = compare(expected, observed, **scope)
    assert matched["supplied_files_match"]
    assert matched["expected_events"] == len(values)
    assert not matched["live_splunk_verified"]
    observed.write_text("".join(json.dumps(value) + "\n" for value in values[:-1]))
    assert compare(expected, observed, **scope)["missing_events"] == 1
    with pytest.raises(TelemetryCheckError, match="outside"):
        compare(expected, full_package / name / "reset-events.jsonl", **scope)


def test_explicit_execution_requires_new_output(tmp_path):
    with pytest.raises(SystemExit) as error:
        rehearsal.main(["--execute"])
    assert error.value.code == 2
    directory = tmp_path / "existing"
    directory.mkdir()
    unrelated = directory / "notes.txt"
    unrelated.write_text("preserve this", encoding="utf-8")
    with pytest.raises(ValueError, match="overwrites"):
        rehearsal.run_suite(directory, ["path-pass-pass-pass-pass"])
    assert unrelated.read_text(encoding="utf-8") == "preserve this"
    link = tmp_path / "link"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="overwrites"):
        rehearsal.run_suite(link)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(ValueError, match="overwrites"):
        rehearsal.run_suite(dangling)


@pytest.mark.parametrize(
    "identifiers",
    [[], ["unknown"], ["../escape"], ["missing-cloud-source", "missing-cloud-source"]],
)
def test_case_selection_is_bounded_and_rejected_before_creating_output(
    tmp_path, identifiers
):
    destination = tmp_path / "new"
    with pytest.raises(ValueError):
        rehearsal.run_suite(destination, identifiers)
    assert not destination.exists()


@pytest.mark.parametrize("name", list(rehearsal.cases()))
def test_each_real_case_records_the_expected_result_and_restores_baselines(
    full_package, name
):
    result = load_result(full_package, name)
    definition = rehearsal.cases()[name]
    assert result["verified"] and result["error"] is None
    assert all(item["passed"] for item in result["checks"])
    expected = dict(
        zip(
            ("DP1", "DP2", "DP3", "DP4"),
            (
                "pass" if value else "miss"
                for value in (
                    definition.dp1,
                    definition.dp2,
                    definition.dp3,
                    definition.dp4,
                )
            ),
        )
    )
    if name in {"missing-cloud-source", "cloud-telemetry-fault"}:
        expected = {
            key: value for key, value in expected.items() if key in {"DP1", "DP2"}
        }
    if name == "missing-impact-source":
        expected.pop("DP4")
    assert result["checkpoint_results"] == expected
    assert result["reset"]["impact_baseline_verified"]
    module = importlib.import_module("modules.07-ransomware-sim.impact_actions")
    for run_id in (result["run_id"], result["reset_run_id"]):
        for section in ("live", "known-good"):
            for filename, contents in module.FIXTURE_CONTENTS.items():
                assert (
                    full_package / name / "disposable" / run_id / section / filename
                ).read_bytes() == contents
    bundle = json.loads(
        (full_package / name / "run-review-bundle.json").read_text(encoding="utf-8")
    )
    report = rehearsal.build_report(bundle)
    assert report["status"] == "provisional" and report["reviewed_objectives"] == 0
    assert not any(
        event["event_type"] == "evaluation.objective.judged"
        for event in bundle["events"]
    )
    if name in {"missing-cloud-source", "cloud-telemetry-fault"}:
        assert report["objectives"][3]["observation"]["status"] == "not_observed"


def test_all_sixteen_combinations_are_covered(full_package):
    manifest = json.loads((full_package / "manifest.json").read_text(encoding="utf-8"))
    assert (
        len(
            {
                load_result(full_package, item["case_id"])["case"]["case_id"]
                for item in manifest["cases"]
                if item["case_id"].startswith("path-")
            }
        )
        == 16
    )
    verification = rehearsal.verify_package(full_package)
    assert verification["full_suite"]
    assert verification["cases_verified"] == 24
    assert verification["branch_paths_verified"] == 16
    assert verification["control_fault_cases_verified"] == 8


def test_partial_controls_prevent_fabricated_access_or_rearmed_impact(full_package):
    cloud = load_result(full_package, "partial-cloud-control")
    assert cloud["checkpoint_results"]["DP3"] == "miss"
    assert (
        next(
            item["actual"]
            for item in cloud["checks"]
            if item["name"] == "cloud:actual_access_count"
        )
        == 5
    )
    impact = load_result(full_package, "partial-impact-control")
    assert impact["checkpoint_results"]["DP4"] == "miss"
    assert (
        next(
            item["actual"]
            for item in impact["checks"]
            if item["name"] == "impact:actual_variant"
        )
        == "blocked"
    )


def test_stop_and_partial_io_failures_prove_rollback(full_package):
    for name, check in (
        ("stop-during-impact", "impact:partial_execution_rollback"),
        ("impact-write-fault", "impact:partial_execution_rollback"),
        ("recovery-write-fault", "recovery:partial_write_rollback"),
    ):
        result = load_result(full_package, name)
        assert result["terminal_state"] == "stopped"
        assert next(
            item["passed"] for item in result["checks"] if item["name"] == check
        )
        if name != "recovery-write-fault":
            assert (
                next(
                    item["actual"]
                    for item in result["checks"]
                    if item["name"] == "impact:interrupted_during_second_marker"
                )
                == 2
            )
    stopped = load_result(full_package, "stop-during-impact")
    assert (
        next(
            item["actual"]
            for item in stopped["checks"]
            if item["name"] == "impact:stop_during_second_marker"
        )
        == 2
    )


def test_verifier_is_read_only_no_runtime_or_network(full_package, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline verifier attempted runtime, network or writes")

    original = Path.open

    def read_only(self, mode="r", *args, **kwargs):
        if any(character in mode for character in "wax+"):
            forbidden()
        return original(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only)
    monkeypatch.setattr(rehearsal, "PortalService", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert rehearsal.verify_package(full_package)["verified"]


def test_execution_stays_local_with_network_disabled(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("local runtime attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    output = tmp_path / "local"
    assert rehearsal.run_suite(output, ["partial-cloud-control"])["verified"]
    assert not rehearsal.verify_package(output)["full_suite"]


@pytest.mark.parametrize(
    "mutation",
    [
        "report",
        "event_ledger",
        "decoy",
        "symlink",
        "missing_file",
        "unknown_case",
        "duplicate_case",
        "unknown_path",
        "false_checks",
        "wrong_checkpoint",
        "wrong_reset",
    ],
)
def test_offline_verification_rejects_modified_or_inconsistent_packages(
    full_package, tmp_path, mutation
):
    destination = copy_case(full_package, tmp_path)
    name = "path-pass-pass-pass-pass"
    case_root = destination / name
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "report":
        (case_root / "after-action-review.md").write_text(
            "false report", encoding="utf-8"
        )
    elif mutation == "event_ledger":
        resign_file(destination, "events.jsonl", "{}\n")
    elif mutation == "decoy":
        result = load_result(destination, name)
        (
            case_root / "disposable" / result["run_id"] / "live" / "billing-export.csv"
        ).write_bytes(b"changed synthetic content")
    elif mutation == "symlink":
        original = case_root / "result.json"
        moved = tmp_path / "outside-result.json"
        original.rename(moved)
        original.symlink_to(moved)
    elif mutation == "missing_file":
        (case_root / "result.json").rename(tmp_path / "moved-result.json")
    elif mutation == "unknown_case":
        manifest["cases"][0]["case_id"] = "../outside"
    elif mutation == "duplicate_case":
        manifest["cases"].append(deepcopy(manifest["cases"][0]))
    elif mutation == "unknown_path":
        manifest["cases"][0]["files_sha256"]["../../outside"] = "0" * 64
    else:
        result = load_result(destination, name)
        if mutation == "false_checks":
            result["checks"][0]["passed"] = False
        elif mutation == "wrong_checkpoint":
            result["checkpoint_results"]["DP3"] = "miss"
        else:
            result["reset"]["prior_run_id"] = "different-run"
        resign_file(destination, "result.json", json.dumps(result))
    if mutation in {"unknown_case", "duplicate_case", "unknown_path"}:
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        rehearsal.verify_package(destination)


def test_unexpected_regression_is_not_swallowed_and_keeps_evidence(
    tmp_path, monkeypatch, capsys
):
    def fail(_self):
        raise RuntimeError("unexpected regression")

    monkeypatch.setattr(rehearsal.Driver, "finish", fail)
    destination = tmp_path / "failed"
    name = "path-miss-miss-miss-miss"
    assert (
        rehearsal.main(["--execute", "--output", str(destination), "--case", name]) == 1
    )
    assert "partial evidence retained" in capsys.readouterr().err
    result = load_result(destination, name)
    assert not result["verified"] and "unexpected regression" in result["error"]
    assert (destination / name / "events.jsonl").stat().st_size > 0
    with pytest.raises(ValueError, match="failed"):
        rehearsal.verify_package(destination)


def test_cli_read_only_verify_and_mutually_exclusive_flags(full_package, capsys):
    assert rehearsal.main(["--verify", str(full_package)]) == 0
    assert json.loads(capsys.readouterr().out)["cases_verified"] == 24
    with pytest.raises(SystemExit):
        rehearsal.main(["--verify", str(full_package), "--execute"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("verified", "true"),
        ("source", []),
        ("runtime", None),
        ("created_at", "not-a-date"),
    ],
)
def test_invalid_package_metadata_is_rejected(full_package, tmp_path, field, value):
    destination = copy_case(full_package, tmp_path)
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        rehearsal.verify_package(destination)


def test_hardlinked_artifact_is_rejected(full_package, tmp_path):
    destination = copy_case(full_package, tmp_path)
    source = destination / "path-pass-pass-pass-pass" / "result.json"
    (tmp_path / "linked.json").hardlink_to(source)
    with pytest.raises(ValueError, match="regular unlinked"):
        rehearsal.verify_package(destination)


@pytest.mark.parametrize("value", [None, [], {"reset": None}])
def test_malformed_result_returns_cli_failure(full_package, tmp_path, value, capsys):
    destination = copy_case(full_package, tmp_path)
    resign_file(destination, "result.json", json.dumps(value))
    assert rehearsal.main(["--verify", str(destination)]) == 1
    assert "malformed case result" in capsys.readouterr().err


def test_reset_failure_preserves_available_events(tmp_path, monkeypatch):
    def fail(_self):
        raise RuntimeError("reset regression")

    monkeypatch.setattr(rehearsal.Driver, "reset", fail)
    destination = tmp_path / "failed-reset"
    name = "path-pass-pass-pass-pass"
    manifest = rehearsal.run_suite(destination, [name])
    assert manifest["verified"] is False
    assert (destination / name / "events.jsonl").stat().st_size > 0
    failure = json.loads((destination / name / "failure.json").read_text())
    assert failure["verified"] is False
    assert "reset regression" in failure["error"]


def test_ci_executes_and_independently_verifies_without_ignoring_failure():
    workflow = (rehearsal.ROOT / ".github/workflows/local-rehearsal-ci.yml").read_text()
    assert "scripts/rehearsal.py --execute" in workflow
    assert "scripts/rehearsal.py --verify" in workflow
    assert "if: always()" in workflow
    assert "|| true" not in workflow
    assert "continue-on-error" not in workflow


def source_for_package(root):
    source = json.loads((root / "manifest.json").read_text())["source"]
    source["git_revision"] = "a" * 40
    source["working_tree_dirty"] = False
    return source


def set_package_source(root, source):
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source"] = source
    path.write_text(json.dumps(manifest))


def test_current_source_verification_is_read_only(full_package, tmp_path, monkeypatch):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    set_package_source(root, source)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(rehearsal, "_source", lambda: deepcopy(source))
    report = rehearsal.verify_package(root, require_current_source=True)
    assert report["verified"] is True
    assert report["full_suite"] is False  # Source match is not a full-coverage claim.
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("side", ["package", "checkout"])
@pytest.mark.parametrize("change", ["revision", "unknown", "dirty", "unknown-dirty", "hash", "missing", "extra"])
def test_current_source_rejects_mismatched_or_uncertain_provenance(
    full_package, tmp_path, monkeypatch, side, change
):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    current = deepcopy(source)
    altered = source if side == "package" else current
    if change == "revision":
        altered["git_revision"] = "b" * 40
    elif change == "unknown":
        altered["git_revision"] = None
    elif change == "dirty":
        altered["working_tree_dirty"] = True
    elif change == "unknown-dirty":
        altered["working_tree_dirty"] = None
    elif change == "hash":
        altered["files_sha256"]["dashboard/app.py"] = "f" * 64
    elif change == "missing":
        del altered["files_sha256"]["dashboard/app.py"]
    else:
        altered["files_sha256"]["unrecorded.py"] = "f" * 64
    set_package_source(root, source)
    monkeypatch.setattr(rehearsal, "_source", lambda: current)
    with pytest.raises(ValueError, match="current clean Git checkout"):
        rehearsal.verify_package(root, require_current_source=True)


@pytest.mark.parametrize("revision,dirty", [(None, None), ("a" * 40, True)])
def test_matching_but_unreleasable_sources_are_rejected(
    full_package, tmp_path, monkeypatch, revision, dirty
):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    source.update(git_revision=revision, working_tree_dirty=dirty)
    set_package_source(root, source)
    monkeypatch.setattr(rehearsal, "_source", lambda: source)
    with pytest.raises(ValueError, match="current clean Git checkout"):
        rehearsal.verify_package(root, require_current_source=True)


def test_historical_verification_does_not_require_current_checkout(
    full_package, tmp_path, monkeypatch
):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    source.update(git_revision=None, working_tree_dirty=None)
    set_package_source(root, source)

    def must_not_query_checkout():
        pytest.fail("portable verification must not query current source/Git")

    monkeypatch.setattr(rehearsal, "_source", must_not_query_checkout)
    assert rehearsal.verify_package(root)["verified"] is True


def test_source_match_does_not_bypass_artifact_checks(full_package, tmp_path, monkeypatch):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    set_package_source(root, source)
    monkeypatch.setattr(rehearsal, "_source", lambda: source)
    (root / "path-pass-pass-pass-pass" / "events.jsonl").write_text("tampered\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        rehearsal.verify_package(root, require_current_source=True)


def test_current_source_cli_passes_and_fails_closed(
    full_package, tmp_path, monkeypatch, capsys
):
    root = copy_case(full_package, tmp_path)
    source = source_for_package(root)
    set_package_source(root, source)
    monkeypatch.setattr(rehearsal, "_source", lambda: source)
    options = ["--verify", str(root), "--require-current-source"]
    assert rehearsal.main(options) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    current = deepcopy(source)
    current["working_tree_dirty"] = True
    monkeypatch.setattr(rehearsal, "_source", lambda: current)
    assert rehearsal.main(options) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "current clean Git checkout" in output.err


@pytest.mark.parametrize("options", [[], ["--execute"], ["--case", "path-pass-pass-pass-pass"]])
def test_current_source_flag_requires_verify_without_actions(options, monkeypatch):
    def must_not_run(*_args, **_kwargs):
        pytest.fail("invalid verification flags must not execute or query source")

    monkeypatch.setattr(rehearsal, "run_suite", must_not_run)
    monkeypatch.setattr(rehearsal, "_source", must_not_run)
    with pytest.raises(SystemExit) as error:
        rehearsal.main(["--require-current-source", *options])
    assert error.value.code == 2
