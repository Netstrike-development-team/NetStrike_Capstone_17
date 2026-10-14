"""Developer-only local branch demo; not a Cyber Range acceptance report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from shared.events import EventLedger, EventValidator, entity

from .cloud import CLOUD_SCENARIO_PATH
from .identity_slice import IdentitySliceRun


def run_demo(outcome: str) -> tuple[dict, list[dict]]:
    """Run a repeatable synthetic cloud decision without sleeps or networking."""
    if outcome not in {"contained", "full", "partial"}:
        raise ValueError("unsupported demo outcome")
    events = []
    run = IdentitySliceRun(
        event_sink=events.append, scenario_path=CLOUD_SCENARIO_PATH,
        run_id=f"cloud-demo-{outcome}",
        clock=lambda: datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc),
    )
    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(4500)
    audit = run.cloud.audit[-1]
    run.cloud.submit_assessment(
        principal_id="svc-cloud-backup", confirmed_count=5,
        conclusion="mock_access_only", evidence_ids=[audit["event_id"]],
    )
    if outcome != "full":
        for action_id, target_type, target_id in (
            ("cloud.evidence.preserve", "cloud_bucket", "simcorp-customer-exports"),
            ("cloud.key.revoke", "cloud_key", "svc-cloud-backup-key-01"),
            *(
                [("cloud.policy.restore", "cloud_bucket", "simcorp-customer-exports")]
                if outcome == "contained" else []
            ),
        ):
            result = run.submit_action(
                actor=entity("participant", "demo-cloud-responder", role="cloud_responder"),
                action_id=action_id, target=entity(target_type, target_id),
                idempotency_key=action_id,
            )
            if not result["successful"]:
                raise RuntimeError("demo containment did not execute")
    run.controller.advance_to(5700)
    result = run.cloud.resolve()
    for event in events:
        EventValidator().validate(event)
    summary = {
        "developer_demo_only": True, "run_id": run.run_id,
        "outcome_requested": outcome, "checkpoint_passed": result.passed,
        "confirmed_records": run.cloud.state.exposure[
            "simcorp-customer-exports"
        ]["confirmed_count"],
        "external_transfer_observed": False, "events_validated": len(events),
        "bulk_blocked": any(e["event_type"] == "cloud.bulk_access.blocked" for e in events),
        "extortion_claim_present": any(
            e["event_type"] == "cloud.extortion.claimed" for e in events
        ),
    }
    return summary, events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcome", choices=("contained", "full", "partial"), default="contained")
    parser.add_argument("--events", help="Optional JSONL ledger path; use a new file per run")
    args = parser.parse_args()
    summary, events = run_demo(args.outcome)
    if args.events:
        ledger = EventLedger(args.events)
        for event in events:
            ledger.append(event)
        summary["ledger"] = str(ledger.path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
