"""End-to-end identity vertical-slice integration tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orchestrator.checkpoints import EvidenceReference, IdentityTriageSubmission
from orchestrator.controller import ItemStatus, RunState
from orchestrator.identity_slice import IdentitySliceRun
from shared.actions import ActionContractError
from shared.events import EventLedger, EventValidator, entity, iter_jsonl


NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def _run(events):
    return IdentitySliceRun(
        event_sink=events.append,
        run_id="run-identity-slice",
        clock=lambda: NOW,
    )


def _execute_containment(run: IdentitySliceRun) -> None:
    actions = (
        (
            entity("participant", "learner-identity", role="identity_responder"),
            "identity.session.revoke",
            entity("session", "sess-red-01"),
        ),
        (
            entity("participant", "learner-identity", role="identity_responder"),
            "identity.factor.remove",
            entity("mfa_factor", "factor-red-01"),
        ),
        (
            entity("participant", "learner-identity", role="identity_responder"),
            "identity.credential.reset",
            entity("identity", "sarah"),
        ),
        (
            entity("participant", "learner-endpoint", role="endpoint_responder"),
            "endpoint.host.isolate",
            entity("host", "FIN-WS01"),
        ),
        (
            entity("participant", "learner-endpoint", role="endpoint_responder"),
            "evidence.artifact.preserve",
            entity("evidence_artifact", "FIN-WS01-discovery-bundle"),
        ),
    )
    for index, (actor, action_id, target) in enumerate(actions, start=1):
        result = run.submit_action(
            actor=actor,
            action_id=action_id,
            target=target,
            idempotency_key=f"containment-{index}",
        )
        assert result["successful"] is True


def test_preparation_stages_searchable_identity_history_with_one_sequence() -> None:
    events = []
    run = _run(events)

    run.controller.prepare()

    event_types = [event["event_type"] for event in events]
    assert "identity.fake_sso.submitted" in event_types
    assert "helpdesk.identity_reset.completed" in event_types
    assert "identity.factor.registered" in event_types
    assert "identity.session.created" in event_types
    assert "endpoint.remote_access.succeeded" in event_types
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert all(event["run_id"] == "run-identity-slice" for event in events)
    for event in events:
        EventValidator().validate(event)


def test_complete_identity_slice_selects_contained_branch_from_state() -> None:
    events = []
    run = _run(events)
    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(2400)

    dp1 = run.submit_dp1(
        IdentityTriageSubmission(
            affected_identity="Sarah Mitchell (sarah)",
            classification="Likely account compromise",
            evidence=(
                EvidenceReference("HD-1042", "helpdesk"),
                EvidenceReference("factor-red-01", "identity"),
                EvidenceReference("sess-red-01", "identity"),
            ),
        )
    )
    assert dp1.passed is True

    _execute_containment(run)
    run.controller.advance_to(5100)
    dp2 = run.resolve_dp2()

    assert dp2.passed is True
    assert run.controller.items["ACT-04A"].status == ItemStatus.DELIVERED
    assert run.controller.items["ACT-04B"].status == ItemStatus.SKIPPED
    assert run.automation.state.blocked_post_containment_auth is True
    assert any(
        event["event_type"] == "identity.authentication.blocked"
        for event in events
    )
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )


def test_incomplete_containment_selects_adverse_branch() -> None:
    events = []
    run = _run(events)
    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(5100)

    result = run.resolve_dp2()

    account = run.endpoint_state.accounts["svc-print-sync"]
    assert result.passed is False
    assert account == {
        "exists": True,
        "enabled": True,
        "groups": ["SimCorp-Server-Operators"],
    }
    assert run.controller.items["ACT-04B"].status == ItemStatus.DELIVERED
    assert any(
        event["event_type"] == "directory.group.membership.changed"
        for event in events
    )


def test_participant_action_policy_is_enforced_by_real_adapter() -> None:
    events = []
    run = _run(events)
    run.controller.start()

    denied = run.submit_action(
        actor=entity("participant", "observer", role="observer"),
        action_id="identity.session.revoke",
        target=entity("session", "sess-red-01"),
        idempotency_key="unauthorized-revoke",
    )

    assert denied["successful"] is False
    assert denied["error_code"] == "role_denied"
    assert run.identity_state.sessions["sess-red-01"]["active"] is True

    with pytest.raises(ActionContractError, match="not available"):
        run.submit_action(
            actor=entity("participant", "observer", role="observer"),
            action_id="identity.account.delete",
            target=entity("identity", "sarah"),
            idempotency_key="unsafe-delete",
        )


def test_jsonl_ledger_accepts_interleaved_controller_module_and_action_events(
    tmp_path,
) -> None:
    ledger = EventLedger(tmp_path / "identity-slice.jsonl", clock=lambda: NOW)
    run = IdentitySliceRun(
        event_sink=ledger.append,
        run_id="run-ledger-integration",
        clock=lambda: NOW,
    )

    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(900)

    persisted = list(iter_jsonl(ledger.path))
    assert ledger.event_count == len(persisted)
    assert [event["sequence"] for event in persisted] == list(
        range(1, len(persisted) + 1)
    )
    assert {event["source"]["kind"] for event in persisted} == {
        "action_adapter",
        "controller",
        "module",
    }


def test_fail_safe_blocks_actions_and_reset_rebuilds_clean_state() -> None:
    events = []
    run = _run(events)
    run.controller.prepare()
    run.controller.start()
    run.fail_safe_stop("integration safety test")

    denied = run.submit_action(
        actor=entity("participant", "learner-identity", role="identity_responder"),
        action_id="identity.session.revoke",
        target=entity("session", "sess-red-01"),
        idempotency_key="after-stop",
    )
    assert denied["error_code"] == "run_stopped"

    run.reset(new_run_id="run-after-reset")

    assert run.controller.state == RunState.READY
    assert run.run_id == "run-after-reset"
    assert run.identity_state.readiness_mismatches() == ()
    assert run.endpoint_state.readiness_mismatches() == ()
    new_run_events = [event for event in events if event["run_id"] == "run-after-reset"]
    assert [event["sequence"] for event in new_run_events] == [1]
