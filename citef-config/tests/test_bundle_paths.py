"""Check bundle path templates without running Ansible."""

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined


ROLES = Path(__file__).resolve().parents[1] / "roles"


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("Administrator", "Administrator"),
        ("SIMCORP/Administrator", "Administrator"),
        ("SIMCORP\\Administrator", "Administrator"),
        ("SIMCORP\\\\Administrator", "Administrator"),
        ("Administrator@SIMCORP.TEST", "Administrator@SIMCORP.TEST"),
        ("admin@alternate.test", "admin@alternate.test"),
    ],
)
def test_linux_join_lets_realmd_select_realm_for_unqualified_accounts(username, expected):
    tasks = yaml.safe_load((ROLES / "linux_baseline/tasks/main.yml").read_text())
    task = next(
        task for task in tasks
        if task["name"] == "Join Linux host to the exercise domain"
    )
    command = task["ansible.builtin.command"]
    user_template = command["argv"][command["argv"].index("--user") + 1]
    # Plain Jinja does not reproduce Ansible's escaping of backslashes in literals.
    assert "\\" not in user_template
    engine = Environment(undefined=StrictUndefined)
    engine.filters["split"] = lambda value, separator: value.split(separator)
    variables = {
        "domain_admin_user": username,
        "domain_admin_password": "synthetic-test-password",
        "identity_baseline": {
            "domain_dns_name": "simcorp.test",
            "search_base_dn": "OU=Exercise,DC=simcorp,DC=test",
        },
    }
    argv = [engine.from_string(arg).render(variables) for arg in command["argv"]]
    assert argv[argv.index("--user") + 1] == expected
    assert argv[-1] == "simcorp.test"
    assert argv[argv.index("--computer-ou") + 1] == variables["identity_baseline"]["search_base_dn"]
    assert engine.from_string(command["stdin"]).render(variables) == variables["domain_admin_password"]
    assert task["no_log"] is True


def test_linux_prerequisites_are_installed_before_dns_and_time_configuration():
    tasks = yaml.safe_load((ROLES / "linux_baseline/tasks/main.yml").read_text())
    names = [task["name"] for task in tasks]
    ordered_tasks = [
        "Require Ubuntu 26.04 for the bundled Linux membership packages",
        "Remove stale Linux domain package files",
        "Stage Linux Active Directory package bundle",
        "Install Linux Active Directory packages without downloading",
    ]
    indices = [names.index(name) for name in ordered_tasks]
    assert indices == sorted(indices)
    install_index = indices[-1]
    for name in (
        "Configure internal DNS and exercise search domain",
        "Configure approved NTP sources and root distance",
        "Ensure systemd-resolved is enabled",
        "Ensure the system resolver uses systemd-resolved",
        "Ensure chrony is enabled",
        "Apply DNS and time changes before verification",
        "Verify every approved forward DNS record",
        "Check existing Linux domain membership",
    ):
        assert install_index < names.index(name)
    install = tasks[install_index]["ansible.builtin.shell"]
    assert "--no-download" in install
    assert "Dir::Cache::archives=/var/cache/netstrike-linux-domain-packages" in install


@pytest.mark.parametrize("override", [None, "/srv/offline-bundle/netstrike-offline-bundle"])
def test_linux_packages_follow_controller_bundle_selection(tmp_path, override):
    playbook_dir = tmp_path / "citef-config" / "playbooks"
    variables = {
        "playbook_dir": str(playbook_dir),
        "offline_artifacts": {"directory": "offline-bundles/CITEF-RELEASE"},
    }
    if override is not None:
        variables["controller_offline_bundle_root"] = override
    engine = Environment(undefined=StrictUndefined)
    baseline = yaml.safe_load((ROLES / "linux_baseline/tasks/main.yml").read_text())
    controller = yaml.safe_load((ROLES / "controller_service/tasks/main.yml").read_text())
    copy_task = next(
        task for task in baseline
        if task["name"] == "Stage Linux Active Directory package bundle"
    )
    paths_task = next(
        task for task in controller
        if task["name"] == "Define controller release and artifact paths"
    )
    source = engine.from_string(copy_task["ansible.builtin.copy"]["src"]).render(variables)
    bundle = engine.from_string(
        paths_task["ansible.builtin.set_fact"]["controller_bundle_root"]
    ).render(variables)
    expected = (
        Path(override) if override is not None
        else tmp_path / "offline-bundles/CITEF-RELEASE/netstrike-offline-bundle"
    )

    assert Path(bundle).resolve() == expected
    assert Path(source).resolve() == expected / "destinations/CTRL01/linux-packages"
    assert variables["offline_artifacts"]["directory"] == "offline-bundles/CITEF-RELEASE"
