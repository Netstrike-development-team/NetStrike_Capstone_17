"""Explicit-execution developer demo of marker-only impact and recovery."""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.events import EventLedger, EventValidator, entity

from .checkpoints import EvidenceReference, IdentityTriageSubmission
from .identity_slice import IdentitySliceRun
from .impact import FULL_SCENARIO_PATH

DEMO_TIME = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)


def run_demo(outcome, root, *, run_id=None):
    """Use only a supplied dedicated root; this is not a release acceptance run."""
    if outcome not in {"blocked", "realized", "partial"}:
        raise ValueError("unsupported impact demo outcome")
    events = []
    run = IdentitySliceRun(
        event_sink=events.append, scenario_path=FULL_SCENARIO_PATH, impact_root=root,
        run_id=run_id or f"impact-demo-{uuid.uuid4()}",
        clock=lambda: DEMO_TIME,
    )
    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(1500)
    run.submit_dp1(IdentityTriageSubmission(
        affected_identity="sarah", classification="account compromise",
        evidence=(EvidenceReference("HD-1042", "helpdesk"),
                  EvidenceReference("factor-red-01", "identity"),
                  EvidenceReference("sess-red-01", "identity")),
    ))
    run.controller.advance_to(3600)
    run.resolve_dp2()
    run.controller.advance_to(5700)
    run.cloud.resolve()
    if outcome != "realized":
        actions = [("endpoint.process.stop", "process", "impact-task-01")]
        if outcome == "blocked":
            actions.extend([
                ("endpoint.host.isolate", "host", "FIN-WS01"),
                ("ad.persistence.remove", "directory_account", "svc-print-sync"),
            ])
        for action_id, target_type, target_id in actions:
            result = run.submit_action(
                actor=entity("participant", "demo-endpoint", role="endpoint_responder"),
                action_id=action_id, target=entity(target_type, target_id),
                idempotency_key=action_id,
            )
            if not result["successful"]:
                raise RuntimeError("demo containment failed")
    run.controller.advance_to(6600)
    prevention = run.impact.resolve()
    before_recovery = run.impact.fixture.inspect()
    actual_variant = run.impact.fixture.last_report["variant"]
    for action_id in ("recovery.fixture.restore", "recovery.health.validate"):
        result = run.impact.recover(
            actor=entity("participant", "demo-recovery", role="cloud_responder"),
            action_id=action_id, fixture_id="FILE01-disposable-fixture",
            key=action_id, dry_run=False,
        )
        if not result["successful"]:
            raise RuntimeError("demo recovery failed")
    run.impact.submit_brief({
        "confirmed_scope": "Synthetic identity, endpoint and customer-export incident.",
        "confirmed_cloud_records": 25,
        "business_impact": "Only disposable exercise data was affected.",
        "actions_taken": "Applied approved containment, restored decoys and verified hashes.",
        "remaining_risk": "Mock access does not prove external transfer.",
        "recommendations": ["Strengthen helpdesk verification.", "Review service-key privileges."],
        "evidence_ids": [run.impact.validation_event_id],
    })
    run.controller.advance_to(7800)
    for event in events:
        EventValidator().validate(event)
    return {
        "developer_demo_only": True, "dry_run": False, "run_id": run.run_id,
        "impact_outcome_requested": outcome, "dp4_prevention_passed": prevention.passed,
        "actual_marker_variant": actual_variant,
        "available_before_recovery": before_recovery["available_originals"],
        "originals_unchanged": before_recovery["originals_unchanged"],
        "baseline_restored": run.impact.fixture.inspect()["baseline_verified"],
        "recovery_observations_passed": run.impact.final_review.passed,
        "play_state": run.controller.state.value, "play_seconds": 7800,
        "encryption_performed": False, "events_validated": len(events),
        "fixed_demo_clock": DEMO_TIME.isoformat(),
    }, events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcome", choices=("blocked", "realized", "partial"), default="blocked")
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly create/move/restore decoys",
    )
    parser.add_argument(
        "--root", help="Existing dedicated disposable root; otherwise use a temporary one",
    )
    parser.add_argument("--run-id", help="New safe run directory ID; never reuse a run")
    parser.add_argument("--events", help="Optional new JSONL ledger path (requires --execute)")
    args = parser.parse_args()
    if args.events and (Path(args.events).exists() or Path(args.events).is_symlink()):
        parser.error("--events must be a new local file")
    if not args.execute:
        if args.events:
            parser.error("--events requires --execute")
        print(json.dumps({
            "dry_run": True, "writes_performed": False,
            "impact_outcome_requested": args.outcome,
            "message": "Preview only. Use --execute to run five disposable decoys.",
        }, indent=2))
        return
    if args.root:
        summary, events = run_demo(args.outcome, args.root, run_id=args.run_id)
        summary["fixture_retained"] = True
    else:
        with tempfile.TemporaryDirectory(prefix="netstrike-impact-demo-") as demo_root:
            summary, events = run_demo(args.outcome, demo_root, run_id=args.run_id)
        summary["fixture_retained"] = False
    if args.events:
        ledger = EventLedger(args.events, clock=lambda: DEMO_TIME)
        for event in events:
            ledger.append(event)
        summary["ledger"] = str(ledger.path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
