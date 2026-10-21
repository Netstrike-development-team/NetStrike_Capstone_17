"""Check Windows forwarder lifecycle ordering without running Ansible."""

from pathlib import Path

import yaml


ROLE = Path(__file__).resolve().parents[1] / "roles/windows_telemetry"
HANDLER = "Restart Windows Universal Forwarder"


def test_forwarder_install_defers_first_start_until_configuration_is_complete():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    install = next(t for t in tasks if "ansible.windows.win_package" in t)
    package = install["ansible.windows.win_package"]
    assert package["creates_service"] == "SplunkForwarder"
    assert "LAUNCHSPLUNK=0" in package["arguments"]

    flushes = [
        i for i, task in enumerate(tasks)
        if task.get("ansible.builtin.meta") == "flush_handlers"
    ]
    assert len(flushes) == 1
    flush = flushes[0]
    notifications = [
        i for i, task in enumerate(tasks) if task.get("notify") == HANDLER
    ]
    assert notifications
    assert all(i < flush for i in notifications)
    assert tasks[flush - 1]["name"] == "Fail if Sysmon is not installed and running"

    starts = [
        (i, task["ansible.windows.win_service"])
        for i, task in enumerate(tasks)
        if task.get("ansible.windows.win_service", {}).get("name") == "SplunkForwarder"
        and task["ansible.windows.win_service"].get("state") in ("started", "restarted")
    ]
    assert len(starts) == 1
    position, service = starts[0]
    assert position > flush
    assert service["state"] == "started"
    assert service["start_mode"] == "auto"

    account = next(
        task["ansible.windows.win_service"] for task in tasks
        if task.get("ansible.windows.win_service", {}).get("name") == "SplunkForwarder"
        and "username" in task["ansible.windows.win_service"]
    )
    assert account["username"] == "LocalSystem"
    assert "state" not in account


def test_forwarder_changes_share_one_pending_state_aware_handler():
    handlers = yaml.safe_load((ROLE / "handlers/main.yml").read_text())
    assert len(handlers) == 1
    assert handlers[0]["name"] == HANDLER
    script = handlers[0]["ansible.windows.win_powershell"]["script"]
    assert "$ErrorActionPreference = 'Stop'" in script
    assert "[TimeSpan]::FromSeconds(120)" in script
    assert "if ($service.Status -eq 'StartPending')" in script
    assert "if ($service.Status -ne 'Stopped' -and $service.Status -ne 'StopPending')" in script
    stop = script.index("$service.Stop()")
    wait = script.index("$service.WaitForStatus('Stopped', $timeout)")
    start = script.index("$service.Start()")
    assert stop < wait < start
    assert script.index("$service.WaitForStatus('Running', $timeout)", start) > start
