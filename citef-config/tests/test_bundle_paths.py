"""Check bundle path templates without running Ansible."""

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined


ROLES = Path(__file__).resolve().parents[1] / "roles"


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
