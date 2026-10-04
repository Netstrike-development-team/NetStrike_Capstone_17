"""Contained developer publication demonstration, not live Splunk/range testing."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .auth import PortalPrincipal
from .event_spool import SpoolError, _path, _write, export
from .service import PortalService
from .store import PortalStore

EXERCISE = "operation-silent-spider"


def plan():
    """Default preview: no fixture, database, server, network or export is created."""
    return {
        "developer_demo_only": True,
        "writes_performed": False,
        "scenario": "identity-slice",
        "steps": [
            "start synthetic partial play",
            "publish private opening evidence",
            "stop and archive/reset",
            "start/stop a fresh partial run",
            "publish old/new evidence without duplicates",
        ],
        "live_splunk_verified": False,
        "full_exercise_completed": False,
    }


def demonstrate(output):
    """Use the real service and exporter, but do not serve a UI or contact a SIEM."""
    root = _path(output)
    if root.exists() or root.is_symlink():
        raise SpoolError("demo requires a new output directory")
    root.mkdir(mode=0o700)
    database = root / "portal.sqlite3"
    store = PortalStore(database)
    service = PortalService(store, run_id="spool-demo-before-reset")
    principal = PortalPrincipal("developer-demo-facilitator", "facilitator")
    destination = root / "staff-spool"
    try:
        service.start_run(principal)
        opening = export(database, destination, exercise_id=EXERCISE, execute=True)
        service.run.fail_safe_stop("Developer spool demo: intentionally partial play")
        reset = service.reset_run(
            new_run_id="spool-demo-after-reset", principal=principal
        )
        service.start_run(principal)
        service.run.fail_safe_stop("Developer spool demo: fresh partial play")
        following = export(database, destination, exercise_id=EXERCISE, execute=True)
        repeated = export(database, destination, exercise_id=EXERCISE, execute=True)
        if (
            opening["events_remaining"]
            or following["events_remaining"]
            or repeated["events_selected"]
        ):
            raise SpoolError("demonstration publication invariant failed")
        archived = service.review_archive(reset["reset"]["review_archive_id"])
        result = {
            **plan(),
            "writes_performed": True,
            "opening": opening,
            "after_reset": following,
            "repeat": repeated,
            "archive_review_status": archived["report"]["status"],
            "archive_run_state": archived["report"]["run_state"],
            "current_run_state": service.run.controller.state.value,
            "participant_ingestion_configured": False,
        }
        _write(
            root / "demo-summary.json", (json.dumps(result, indent=2) + "\n").encode()
        )
        return result
    finally:
        if service.run.controller.state.value in {"running", "paused"}:
            service.run.fail_safe_stop("Developer demo stopped after failure")
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.execute and args.output is None:
        parser.error("--execute requires --output pointing to a new directory")
    try:
        result = demonstrate(args.output) if args.execute else plan()
    except (OSError, sqlite3.Error, ValueError):
        print(
            "Developer demo failed; preserve its partial evidence and inspect locally.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
