"""Maintained exercise exporter reuses local extractors and preserves uncertainty."""

import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

from shared.profiles import ProfileCatalog, ProfileInitializationError
import pytest

exporter = importlib.import_module("modules.01-osint-profiler.exercise_profiles")
ROOT = Path(__file__).resolve().parents[3]


def test_export_is_repeatable_and_matches_committed_startup_fixture(monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("exercise profiles must come from the local reviewed fixture")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    first = exporter.build_exercise_bundle()
    assert first == exporter.build_exercise_bundle()
    committed = json.loads((ROOT / "orchestrator/fixtures/identity-profiles.v1.json").read_text())
    assert first == committed
    assert all(".com" not in str(profile) for profile in first["profiles"])
    assert all(candidate["confidence"] == "inferred" for profile in first["profiles"] for candidate in profile["email_candidates"])


def test_different_seed_changes_profile_ids_without_changing_reviewed_people():
    first = exporter.build_exercise_bundle()
    second = exporter.build_exercise_bundle("alternative-reviewed-seed")
    assert first["profiles"][0]["id"] != second["profiles"][0]["id"]
    assert first["profiles"][0]["name"] == second["profiles"][0]["name"]
    with pytest.raises(ProfileInitializationError):
        exporter.build_exercise_bundle("https://external.invalid")


def test_cli_export_loads_without_legacy_profiler_output(tmp_path):
    output = tmp_path / "exercise-profiles.json"
    result = subprocess.run([sys.executable, "-m", "modules.01-osint-profiler.exercise_profiles",
                             "--output", str(output)], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    loaded = ProfileCatalog.load(output, expected_seed=exporter.DEFAULT_SEED,
                                 identity_employee_id="emp_001", helpdesk_employee_id="emp_005")
    assert loaded.context()["identity"]["username"] == "sarah@simcorp.test"
