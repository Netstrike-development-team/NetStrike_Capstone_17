"""Render real deployment inputs, then exercise the real application factory."""

import json
import os
import shlex
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jinja2 import Environment, StrictUndefined

from dashboard.app import create_default_app
from dashboard.configuration import ConfigurationError, inspect_configuration
from dashboard.service import PortalService
from dashboard.store import PortalStore

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "citef-config/roles/controller_service"
TOKEN = "synthetic-deployment-staff-credential-only"
RUN_ID = "deployment-run-20261018"
SCENARIOS = {"identity": "identity-slice.v1.json", "cloud": "cloud-slice.v1.json",
             "full-play": "full-play.v1.json"}


def render(tmp_path, scope=None):
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    selected = scope or defaults["controller_scenario_scope"]
    engine = Environment(undefined=StrictUndefined)
    engine.filters["to_json"] = json.dumps
    raw = engine.from_string((ROLE / "templates/controller.env.j2").read_text()).render(
        controller_scenario_scope=selected,
        controller_scenario_file=SCENARIOS[selected], exercise_run_id=RUN_ID,
        controller_identity_audit_key="synthetic-deployment-audit-key-" + "x" * 32,
        controller={"sso_allowed_origins": ["http://testserver"]},
        controller_service_tokens={TOKEN: {"actor_id": "fac-01", "role": "facilitator"}},
    )
    # Synthetic assignments only: no shell execution or real secrets.
    injected = dict(shlex.split(line)[0].split("=", 1) for line in raw.splitlines() if line)
    assert injected["NETSTRIKE_RUN_ID"] == RUN_ID
    assert injected["NETSTRIKE_HOST_TELEMETRY_RUN_ID"] == RUN_ID
    assert injected["NETSTRIKE_EXPECTED_SCENARIO_SCOPE"] == selected
    assert injected["NETSTRIKE_SCENARIO_PATH"] == "/opt/netstrike/current/orchestrator/scenarios/" + SCENARIOS[selected]
    # Only relocate VM paths into this test's disposable workspace.
    injected["NETSTRIKE_SCENARIO_PATH"] = str(ROOT / "orchestrator/scenarios" / SCENARIOS[selected])
    injected["NETSTRIKE_PROFILE_FIXTURE"] = str(ROOT / "orchestrator/fixtures/identity-profiles.v1.json")
    injected["NETSTRIKE_PORTAL_DATABASE"] = str(tmp_path / "portal.sqlite3")
    injected["NETSTRIKE_IMPACT_ROOT"] = str(tmp_path / "fixtures")
    (tmp_path / "fixtures").mkdir()
    return injected


def inject(monkeypatch, environment):
    for key in list(os.environ):
        if key.startswith("NETSTRIKE_"):
            monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)


def test_spool_service_renders_two_separate_publishers_with_same_scope():
    engine = Environment(undefined=StrictUndefined)
    raw = engine.from_string((ROLE / "templates/netstrike-event-spool.service.j2").read_text()).render()
    commands = [line for line in raw.splitlines() if line.startswith(("ExecStart=/opt", "ExecStartPost=/opt"))]
    assert "dashboard.event_spool" in commands[0]
    assert "dashboard.learner_spool" in commands[1]
    assert "--source-spool /var/lib/netstrike/event-spool" in commands[1]
    assert "--output /var/lib/netstrike/learner-event-spool" in commands[1]
    assert all("--exercise-id operation-silent-spider" in line and "--execute" in line for line in commands[:2])
    assert "ExecStartPost=-" not in raw
    assert "User=netstrike" in raw and "Group=netstrike" in raw
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    creation = next(t for t in tasks if t["name"] == "Create separate event spool directories readable by the staff group")
    assert creation["loop"] == ["/var/lib/netstrike/event-spool", "/var/lib/netstrike/learner-event-spool"]
    assert creation["ansible.builtin.file"]["mode"] == "0750"


@pytest.mark.parametrize("scope", [None, "identity", "cloud"])
def test_real_template_selects_expected_scope_and_run_before_factory_start(tmp_path, monkeypatch, scope):
    environment = render(tmp_path, scope)
    report, configuration = inspect_configuration(environment)
    assert report["configuration_valid"] and configuration is not None
    assert report["selected_scenario_scope"] == (scope or "full-play")
    assert configuration.host_telemetry_run_id == RUN_ID
    assert not (tmp_path / "portal.sqlite3").exists()
    assert not list((tmp_path / "fixtures").iterdir())
    inject(monkeypatch, environment)
    auth = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_default_app()) as client:
        readiness = client.get("/api/facilitator/readiness", headers=auth).json()
        assert readiness["run_id"] == RUN_ID and readiness["ready_to_prepare"]
        assert not readiness["external_readiness_verified"]
        assert next(c for c in readiness["checks"] if c["check_id"] == "configured_host_telemetry_run")["passed"]
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Synthetic deployment test"}).status_code == 200
    if scope is None:
        assert len(list((tmp_path / "fixtures" / RUN_ID / "live").iterdir())) == 5
        assert readiness["scenario_id"] == "silent-spider-full-play-v1"


@pytest.mark.parametrize("scope", [None, "identity", "cloud"])
def test_reset_preserves_evidence_but_blocks_reentry_with_stale_host_binding(tmp_path, monkeypatch, scope):
    inject(monkeypatch, render(tmp_path, scope))
    auth = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_default_app()) as client:
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "End synthetic run"}).status_code == 200
        reset = client.post("/api/facilitator/reset", headers=auth, json={"new_run_id": "deployment-next-run"})
        assert reset.status_code == 200 and reset.json()["reset"]["review_archive_id"]
        report = client.get("/api/facilitator/readiness", headers=auth).json()
        assert report["run_id"] == "deployment-next-run"
        assert report["blockers"] == ["configured_host_telemetry_run"]
        assert not report["ready_to_prepare"] and not report["ready_to_start"]
        for operation in ("prepare", "start"):
            response = client.post("/api/facilitator/" + operation, headers=auth)
            assert response.status_code == 409
            assert "configured_host_telemetry_run" in response.text
        # No old ID reuse, silent relabelling of host events or evidence deletion.
        connection = sqlite3.connect((tmp_path / "portal.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            assert connection.execute("SELECT count(*) FROM events WHERE run_id = ?", (RUN_ID,)).fetchone()[0] > 0
        finally:
            connection.close()
        assert (tmp_path / "portal.sqlite3").is_file()
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Safety access still available"}).status_code == 200


def test_unbound_local_full_play_can_reset_and_start_again(tmp_path, monkeypatch):
    environment = render(tmp_path)
    environment.pop("NETSTRIKE_HOST_TELEMETRY_RUN_ID")
    inject(monkeypatch, environment)
    auth = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_default_app()) as client:
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Local demo"}).status_code == 200
        assert client.post("/api/facilitator/reset", headers=auth, json={"new_run_id": "unbound-next-run"}).status_code == 200
        report = client.get("/api/facilitator/readiness", headers=auth).json()
        assert report["ready_to_prepare"] and report["blockers"] == []
        assert client.post("/api/facilitator/start", headers=auth).status_code == 200
        assert client.post("/api/facilitator/stop", headers=auth, json={"reason": "Local demo complete"}).status_code == 200


@pytest.mark.parametrize("value,remove_run", [("other-run", False), ("", False),
                                                ("private/value", False), (RUN_ID, True)])
def test_binding_mismatch_or_missing_explicit_run_fails_before_startup_writes(tmp_path, monkeypatch, value, remove_run):
    environment = render(tmp_path)
    environment["NETSTRIKE_HOST_TELEMETRY_RUN_ID"] = value
    if remove_run:
        environment.pop("NETSTRIKE_RUN_ID")
    report, configuration = inspect_configuration(environment)
    assert configuration is None and "configured_host_telemetry_run" in report["blockers"]
    if value:
        assert value not in json.dumps(report)
    inject(monkeypatch, environment)
    with pytest.raises(ConfigurationError, match="configured_host_telemetry_run"):
        create_default_app()
    assert not (tmp_path / "portal.sqlite3").exists()
    assert not list((tmp_path / "fixtures").iterdir())


def test_direct_service_binding_refuses_implicit_or_mismatched_run_before_events():
    store = PortalStore(":memory:")
    try:
        for identifier in (None, "different-run"):
            with pytest.raises(ValueError, match="telemetry"):
                PortalService(store, run_id=identifier, host_telemetry_run_id=RUN_ID)
        assert not store.events("operation-silent-spider", RUN_ID)
    finally:
        store.close()


def test_role_uses_allowlisted_scope_and_systemd_checks_same_intent():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    selection = next(t for t in tasks if t["name"] == "Validate controller exercise selection and run binding")
    assert "controller_scenario_scope in ['identity', 'cloud', 'full-play']" in selection["ansible.builtin.assert"]["that"]
    facts = next(t["ansible.builtin.set_fact"] for t in tasks if t["name"] == "Define controller release and artifact paths")
    expression = facts["controller_scenario_file"]
    engine = Environment(undefined=StrictUndefined)
    for scope, filename in SCENARIOS.items():
        assert engine.from_string(expression).render(controller_scenario_scope=scope) == filename
    service = (ROLE / "templates/netstrike-portal.service.j2").read_text()
    assert "ExecStartPre=/opt/netstrike/venv/bin/python -B -m dashboard.preflight --expect-scope {{ controller_scenario_scope }}" in service
    assert "--workers" not in service


def test_deployment_tests_and_source_templates_are_in_ci_provenance():
    from scripts.rehearsal import _source
    sources = _source()["files_sha256"]
    for path in ("citef-config/tests/test_controller_deployment.py", "citef-config/requirements-test.txt",
                 "citef-config/roles/controller_service/defaults/main.yml",
                 "citef-config/roles/controller_service/tasks/main.yml",
                 "citef-config/roles/controller_service/templates/controller.env.j2",
                 "citef-config/roles/controller_service/templates/netstrike-portal.service.j2"):
        assert path in sources
    workflow = yaml.safe_load((ROOT / ".github/workflows/local-rehearsal-ci.yml").read_text())
    commands = [s.get("run", "") for s in workflow["jobs"]["full-play-rehearsal"]["steps"]]
    assert any("-r citef-config/requirements-test.txt" in command for command in commands)
