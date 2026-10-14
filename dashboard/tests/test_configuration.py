"""Inert deployment preflight, safe diagnostics and fail-before-write startup."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import app as portal_app
from dashboard.app import create_default_app
from dashboard.configuration import (
    ConfigurationError, PortalConfiguration, inspect_configuration, MAX_INPUT_BYTES,
)
from dashboard.store import PortalStore
from orchestrator.cloud import CLOUD_SCENARIO_PATH
from orchestrator.identity_slice import DEFAULT_SCENARIO_PATH
from orchestrator.impact import FULL_SCENARIO_PATH, ROOT_MARKER, ROOT_CONTENT

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "synthetic-config-staff-at-least-24-characters"


def environment(tmp_path, **overrides):
    return {"NETSTRIKE_PORTAL_DATABASE": str(tmp_path / "not-created" / "portal.sqlite3"),
            "NETSTRIKE_RUN_ID": "configuration-run", "NETSTRIKE_IDENTITY_AUDIT_KEY": "synthetic-audit-key-" + "x" * 32,
            "NETSTRIKE_SSO_ALLOWED_ORIGINS": '["http://testserver"]',
            "NETSTRIKE_PORTAL_TOKENS": json.dumps({TOKEN: {"actor_id": "fac-01", "role": "facilitator"}}), **overrides}


def inject(monkeypatch, env):
    for name in list(os.environ):
        if name.startswith("NETSTRIKE_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def scenario(tmp_path, change):
    payload = json.loads(DEFAULT_SCENARIO_PATH.read_text())
    change(payload)
    target = tmp_path / "private-scenario.json"
    target.write_text(json.dumps(payload))
    return str(target)


def no_write(*_args, **_kwargs):
    raise AssertionError("preflight attempted construction or mutation")


def test_preflight_is_inert_and_explicit_about_unverified_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(PortalStore, "__init__", no_write)
    monkeypatch.setattr(Path, "mkdir", no_write)
    monkeypatch.setattr(Path, "write_bytes", no_write)
    original_open = Path.open

    def read_only(self, mode="r", *args, **kwargs):
        assert not any(letter in mode for letter in "wax+")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only)
    report, configuration = inspect_configuration(environment(tmp_path))
    assert report["configuration_valid"] and configuration is not None
    assert report["scope"] == "application_configuration_only"
    assert report["read_only"]
    assert report["selected_scenario_scope"] == "identity"
    assert not report["external_readiness_verified"] and not report["runtime_readiness_verified"]
    assert "database_integrity_or_run_history" in report["not_checked"]
    assert "supervised_clock" in report["not_checked"]
    assert "actual_write_permissions" in report["not_checked"]
    assert not (tmp_path / "not-created").exists()
    serialized = json.dumps(report)
    assert TOKEN not in serialized and str(tmp_path) not in serialized
    assert "synthetic-audit-key" not in repr(configuration)


@pytest.mark.parametrize("field,value,blocker", [
    ("NETSTRIKE_PORTAL_TOKENS", "", "portal_credentials"),
    ("NETSTRIKE_PORTAL_TOKENS", "private-malformed-secret", "portal_credentials"),
    ("NETSTRIKE_PORTAL_TOKENS", "[]", "portal_credentials"),
    ("NETSTRIKE_IDENTITY_AUDIT_KEY", "short-private-secret", "identity_audit_key"),
    ("NETSTRIKE_SSO_ALLOWED_ORIGINS", "not-json-secret", "sso_origins"),
    ("NETSTRIKE_SSO_ALLOWED_ORIGINS", "[]", "sso_origins"),
    ("NETSTRIKE_SSO_ALLOWED_ORIGINS", '"http://testserver"', "sso_origins"),
    ("NETSTRIKE_SSO_ALLOWED_ORIGINS", '["https://private:password@lab.test/path"]', "sso_origins"),
    ("NETSTRIKE_SSO_ALLOWED_ORIGINS", '["https://*.lab.test"]', "sso_origins"),
    ("NETSTRIKE_RUN_ID", "private/path", "run_identifier"),
    ("NETSTRIKE_RUN_ID", "", "run_identifier"),
    ("NETSTRIKE_RUN_ID", "x" * 129, "run_identifier"),
    ("NETSTRIKE_PORTAL_DATABASE", "", "database_target"),
    ("NETSTRIKE_PROFILE_FIXTURE", "/missing/private-profile", "reviewed_profile_bindings"),
    ("NETSTRIKE_SCENARIO_PATH", "/missing/private-scenario", "scenario_definition"),
    ("NETSTRIKE_EXPECTED_SCENARIO_SCOPE", "full-play", "expected_scenario_scope"),
])
def test_invalid_inputs_block_before_store_creation(tmp_path, monkeypatch, field, value, blocker):
    env = environment(tmp_path, **{field: value})
    report, configuration = inspect_configuration(env)
    assert configuration is None and blocker in report["blockers"]
    assert "private" not in json.dumps(report)
    inject(monkeypatch, env)
    monkeypatch.setattr(portal_app, "PortalStore", no_write)
    with pytest.raises(ConfigurationError, match=blocker) as raised:
        create_default_app()
    assert "private" not in str(raised.value)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("record", [
    {"actor_id": 7, "role": "facilitator"}, {"actor_id": "actor", "role": 7},
    {"actor_id": "private actor", "role": "facilitator"}, {"actor_id": "actor", "role": "unknown-private-role"},
    {"actor_id": "actor", "role": "facilitator", "secret": "private"},
])
def test_principal_configuration_is_not_silently_coerced(tmp_path, record):
    report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_PORTAL_TOKENS=json.dumps({TOKEN: record})))
    assert configuration is None and "portal_credentials" in report["blockers"]
    assert "private" not in json.dumps(report)


def test_duplicate_token_keys_and_nested_fields_fail_closed(tmp_path):
    record = '{"actor_id":"actor","role":"facilitator"}'
    duplicates = ['{"' + TOKEN + '":' + record + ',"' + TOKEN + '":' + record + '}',
                  '{"' + TOKEN + '":{"actor_id":"one","actor_id":"two","role":"facilitator"}}']
    for raw in duplicates:
        report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_PORTAL_TOKENS=raw))
        assert configuration is None and "portal_credentials" in report["blockers"]


@pytest.mark.parametrize("change,blocker", [
    (lambda data: data["participant_experience"]["profiles"].update(seed="wrong"), "reviewed_profile_bindings"),
    (lambda data: data["participant_experience"]["sso"].pop("messages"), "sso_experience"),
    (lambda data: data["participant_experience"]["mfa"].update(timeout_seconds=True), "scheduled_mfa_bindings"),
    (lambda data: data["participant_experience"]["mfa"].update(factor_id="not-baseline"), "scheduled_mfa_bindings"),
])
def test_experience_bindings_share_runtime_validation(tmp_path, change, blocker):
    target = scenario(tmp_path, change)
    report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_SCENARIO_PATH=target))
    assert configuration is None and blocker in report["blockers"]
    assert str(tmp_path) not in json.dumps(report)


def test_scenario_input_is_bounded_and_duplicate_fields_rejected(tmp_path):
    target = tmp_path / "scenario.json"
    for raw in ('{"scenario_id":"one","scenario_id":"two"}', " " * (MAX_INPUT_BYTES + 1)):
        target.write_text(raw)
        report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_SCENARIO_PATH=str(target)))
        assert configuration is None and "scenario_definition" in report["blockers"]


@pytest.mark.parametrize("scope,filename", [("identity", DEFAULT_SCENARIO_PATH), ("cloud", CLOUD_SCENARIO_PATH), ("full-play", FULL_SCENARIO_PATH)])
def test_expected_scope_matches_without_enabling_or_provisioning(tmp_path, scope, filename):
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    env = environment(tmp_path, NETSTRIKE_SCENARIO_PATH=str(filename), NETSTRIKE_IMPACT_ROOT=str(disposable))
    report, configuration = inspect_configuration(env, expected_scope=scope)
    assert report["configuration_valid"] and configuration is not None
    assert report["selected_scenario_scope"] == scope
    assert not list(disposable.iterdir())
    wrong, _ = inspect_configuration(env, expected_scope="cloud" if scope != "cloud" else "identity")
    assert "expected_scenario_scope" in wrong["blockers"]


def test_cli_intent_cannot_weaken_configured_expected_scope(tmp_path):
    report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_EXPECTED_SCENARIO_SCOPE="full-play"), expected_scope="identity")
    assert configuration is None and "expected_scenario_scope" in report["blockers"]


@pytest.mark.parametrize("problem", ["missing", "relative", "symlink", "unrelated", "bad-marker", "reused", "unsafe-run"])
def test_full_play_root_blockers_are_inert(tmp_path, problem):
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    env = environment(tmp_path, NETSTRIKE_SCENARIO_PATH=str(FULL_SCENARIO_PATH), NETSTRIKE_IMPACT_ROOT=str(disposable))
    if problem == "missing":
        env.pop("NETSTRIKE_IMPACT_ROOT")
    elif problem == "relative":
        env["NETSTRIKE_IMPACT_ROOT"] = "relative-private-directory"
    elif problem == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(disposable, target_is_directory=True)
        env["NETSTRIKE_IMPACT_ROOT"] = str(alias)
    elif problem == "unrelated":
        (disposable / "private-unrelated.txt").write_text("untouched")
    elif problem == "bad-marker":
        (disposable / ROOT_MARKER).write_bytes(b"not-owned")
    elif problem == "reused":
        (disposable / ROOT_MARKER).write_bytes(ROOT_CONTENT)
        for child in ("live", "known-good", "staging"):
            (disposable / "configuration-run" / child).mkdir(parents=True)
    elif problem == "unsafe-run":
        env["NETSTRIKE_RUN_ID"] = "identity:valid-but-not-directory-safe"
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    report, configuration = inspect_configuration(env)
    assert configuration is None and "disposable_impact_root" in report["blockers"]
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before


def test_existing_owned_root_is_inspected_without_adopting_old_fixture(tmp_path):
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    (disposable / ROOT_MARKER).write_bytes(ROOT_CONTENT)
    for child in ("live", "known-good", "staging"):
        (disposable / "old-run" / child).mkdir(parents=True)
    report, configuration = inspect_configuration(environment(tmp_path, NETSTRIKE_SCENARIO_PATH=str(FULL_SCENARIO_PATH), NETSTRIKE_IMPACT_ROOT=str(disposable)))
    assert report["configuration_valid"] and configuration
    assert not (disposable / "configuration-run").exists()


def test_role_gaps_and_ephemeral_storage_are_warnings_not_invented_readiness(tmp_path):
    env = environment(tmp_path, NETSTRIKE_PORTAL_DATABASE=":memory:",
                      NETSTRIKE_PORTAL_TOKENS=json.dumps({TOKEN: {"actor_id": "learner", "role": "soc_analyst"}}))
    report, _ = inspect_configuration(env)
    assert report["configuration_valid"]
    assert {"no_staff_control_credential", "no_review_credential", "database_is_ephemeral"} <= set(report["warnings"])


def test_cli_missing_config_and_dependencies_are_safe_and_inert(tmp_path):
    env = {name: value for name, value in os.environ.items() if not name.startswith("NETSTRIKE_")}
    env["PYTHONPATH"] = str(ROOT)
    for options in ([], ["-S"]):
        result = subprocess.run([sys.executable, "-B", *options, "-m", "dashboard.preflight"], cwd=tmp_path,
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 1 and not result.stderr
        assert not json.loads(result.stdout)["configuration_valid"]
        assert not list(tmp_path.iterdir())


def test_cli_valid_scope_bad_arguments_and_private_values(tmp_path):
    env = {**os.environ, **environment(tmp_path), "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-B", "-m", "dashboard.preflight", "--expect-scope", "identity"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)["configuration_valid"]
    assert not result.stderr and TOKEN not in result.stdout and str(tmp_path) not in result.stdout
    bad = subprocess.run([sys.executable, "-B", "-m", "dashboard.preflight", "--expect-scope", "private-secret"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert bad.returncode == 2 and "private-secret" not in bad.stderr
    assert not (tmp_path / "not-created").exists()


def test_startup_reuses_validated_auth_and_origin_then_runs_in_memory(tmp_path, monkeypatch):
    env = environment(tmp_path, NETSTRIKE_PORTAL_DATABASE=":memory:")
    inject(monkeypatch, env)
    configuration = PortalConfiguration.from_environment()
    assert configuration.authenticator.authenticate("Bearer " + TOKEN, allowed_roles=frozenset({"facilitator"})).actor_id == "fac-01"
    with TestClient(create_default_app()) as client:
        auth = {"Authorization": "Bearer " + TOKEN}
        state = client.get("/api/facilitator/state", headers=auth)
        assert state.status_code == 200 and state.json()["controller"]["run_id"] == "configuration-run"
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Configuration test"}).status_code == 200


def test_invalid_full_play_credentials_do_not_create_store_marker_or_decoys(tmp_path, monkeypatch):
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    inject(monkeypatch, environment(tmp_path, NETSTRIKE_SCENARIO_PATH=str(FULL_SCENARIO_PATH),
                                  NETSTRIKE_IMPACT_ROOT=str(disposable), NETSTRIKE_PORTAL_TOKENS="private-invalid"))
    with pytest.raises(ConfigurationError, match="portal_credentials"):
        create_default_app()
    assert not list(disposable.iterdir())
    assert not (tmp_path / "not-created").exists()


def test_valid_full_play_only_provisions_at_explicit_startup_not_preflight(tmp_path, monkeypatch):
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    env = environment(tmp_path, NETSTRIKE_PORTAL_DATABASE=":memory:",
                      NETSTRIKE_SCENARIO_PATH=str(FULL_SCENARIO_PATH), NETSTRIKE_IMPACT_ROOT=str(disposable),
                      NETSTRIKE_EXPECTED_SCENARIO_SCOPE="full-play")
    inject(monkeypatch, env)
    assert inspect_configuration(env)[0]["configuration_valid"]
    assert not list(disposable.iterdir())
    with TestClient(create_default_app()) as client:
        assert (disposable / ROOT_MARKER).read_bytes() == ROOT_CONTENT
        assert len(list((disposable / "configuration-run" / "live").iterdir())) == 5
        auth = {"Authorization": "Bearer " + TOKEN}
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Full configuration test"}).status_code == 200
        response = client.post("/api/facilitator/reset", headers=auth, json={"new_run_id": "configuration-next"})
        assert response.status_code == 200 and response.json()["reset"]["review_archive_id"]


def test_validated_credentials_and_origins_are_not_reparsed_after_store_creation(tmp_path, monkeypatch):
    inject(monkeypatch, environment(tmp_path, NETSTRIKE_PORTAL_DATABASE=":memory:"))
    configuration = PortalConfiguration.from_environment()

    def pinned():
        monkeypatch.setenv("NETSTRIKE_PORTAL_TOKENS", "private-invalid")
        monkeypatch.setenv("NETSTRIKE_SSO_ALLOWED_ORIGINS", "private-invalid")
        return configuration

    monkeypatch.setattr(PortalConfiguration, "from_environment", pinned)
    with TestClient(create_default_app()) as client:
        assert client.get("/api/facilitator/state", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200


@pytest.mark.parametrize("stage", ["PortalService", "create_app"])
def test_postvalidation_construction_failure_closes_store_without_deletion(tmp_path, monkeypatch, stage):
    inject(monkeypatch, environment(tmp_path))
    constructed = []

    class TrackingStore(PortalStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed = False
            constructed.append(self)

        def close(self):
            self.closed = True
            super().close()

    def broken_service(*_args, **_kwargs):
        raise RuntimeError("construction failed after validation")

    monkeypatch.setattr(portal_app, "PortalStore", TrackingStore)
    monkeypatch.setattr(portal_app, stage, broken_service)
    with pytest.raises(RuntimeError):
        create_default_app()
    assert constructed[0].closed
    assert (tmp_path / "not-created" / "portal.sqlite3").is_file()


def test_public_package_imports_remain_compatible():
    from dashboard import create_app, create_default_app as exported_factory
    assert create_app is portal_app.create_app
    assert exported_factory is create_default_app
