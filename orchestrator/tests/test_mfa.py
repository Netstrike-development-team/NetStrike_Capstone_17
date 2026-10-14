"""Scheduled human MFA, exercise-clock, containment, and evidence guarantees."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import socket
from copy import deepcopy

import pytest

from orchestrator.controller import ControllerError, ItemStatus
from orchestrator.identity_slice import IdentitySliceRun
from orchestrator.mfa import ScheduledMfa
from orchestrator.scheduler import ScenarioScheduler
from shared.events import EventValidator, entity

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
USER = entity("participant", "synthetic-sarah", role="simulated_user")
FACILITATOR = entity("facilitator", "fac-01", role="facilitator")


def runtime(run_id="run-mfa-test"):
    events = []
    run = IdentitySliceRun(event_sink=events.append, run_id=run_id, clock=lambda: NOW)
    run.controller.prepare()
    run.controller.start()
    return run, events


def mfa_events(events):
    return [event for event in events if event["source"]["component"] == "scheduled-mfa"]


@pytest.mark.parametrize("decision,outcome", [("approve", "approved"), ("deny", "denied")])
@pytest.mark.parametrize("actor", [USER, FACILITATOR])
def test_explicit_decision_is_attributed_correlated_and_never_creates_session(decision, outcome, actor):
    run, events = runtime()
    baseline_sessions = run.identity_state.snapshot()["sessions"]
    run.controller.advance_to(30)
    challenge_id = run.mfa.snapshot()["pending"]["id"]
    assert run.identity_state.mfa["sarah"]["decision"] == "pending"
    run.mfa.decide(challenge_id, decision, actor)

    assert run.mfa.snapshot()["pending"] is None
    assert run.mfa.snapshot()["history"][-1]["outcome"] == outcome
    assert run.identity_state.snapshot()["sessions"] == baseline_sessions
    delivered, decided = mfa_events(events)
    assert decided["actor"] == actor
    assert delivered["data"]["challenge_id"] == decided["data"]["challenge_id"]
    assert decided["correlation_ids"] == [challenge_id, "sess-red-01"]
    with pytest.raises(ControllerError, match="No matching"):
        run.mfa.decide(challenge_id, decision, actor)
    assert len(mfa_events(events)) == 2
    for event in events:
        EventValidator().validate(event)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


def test_time_jump_and_incremental_ticks_have_same_seeded_logical_sequence():
    jump, jump_events = runtime()
    incremental, incremental_events = runtime()
    jump.controller.advance_to(180)
    for second in range(1, 181):
        incremental.controller.advance_to(second)

    def logical(events):
        return [(event["event_type"], event["actor"], event["data"]) for event in mfa_events(events)]

    assert logical(jump_events) == logical(incremental_events)
    assert [event["data"]["elapsed_seconds"] for event in mfa_events(jump_events)] == [30, 60, 90, 120, 150, 180]
    assert [item["outcome"] for item in jump.mfa.snapshot()["history"]] == ["expired"] * 3
    assert jump.identity_state.mfa["sarah"]["push_count"] == 3
    assert jump.identity_state.mfa["sarah"]["decision"] != "approved"
    assert all(jump.controller.items[item].status == ItemStatus.DELIVERED for item in ("MFA-01", "MFA-02", "MFA-03"))


def test_pause_freezes_deadline_and_refuses_decisions_then_resumes():
    run, events = runtime()
    clock = [100.0]
    scheduler = ScenarioScheduler(run.controller, monotonic=lambda: clock[0])
    scheduler.advance_to(30)
    challenge_id = run.mfa.snapshot()["pending"]["id"]
    scheduler.pause()
    clock[0] += 600
    scheduler.tick()
    assert run.mfa.snapshot()["pending"]["expires_in_seconds"] == 30
    with pytest.raises(ControllerError, match="running"):
        run.mfa.decide(challenge_id, "approve", USER)
    scheduler.resume()
    clock[0] += 29
    scheduler.tick()
    assert run.mfa.snapshot()["pending"]["expires_in_seconds"] == 1
    clock[0] += 1
    scheduler.tick()
    assert run.mfa.snapshot()["pending"] is None
    assert mfa_events(events)[-1]["event_type"].endswith("expired")


@pytest.mark.parametrize("action,target_type,target_id,reason", [
    ("identity.account.disable", "identity", "sarah", "account_disabled"),
    ("identity.session.revoke", "session", "sess-red-01", "session_revoked"),
    ("identity.factor.remove", "mfa_factor", "factor-red-01", "factor_removed"),
    ("identity.credential.reset", "identity", "sarah", "credential_rotated"),
])
def test_containment_cancels_pending_and_blocks_future_attempts(action, target_type, target_id, reason):
    run, events = runtime()
    run.controller.advance_to(30)
    challenge_id = run.mfa.snapshot()["pending"]["id"]
    result = run.submit_action(actor=entity("participant", "responder", role="identity_responder"),
                              action_id=action, target=entity(target_type, target_id),
                              idempotency_key="contain-mfa")
    assert result["successful"] is True
    assert run.mfa.snapshot()["pending"] is None
    with pytest.raises(ControllerError, match="No matching"):
        run.mfa.decide(challenge_id, "approve", FACILITATOR)
    run.controller.advance_to(180)
    assert [event["event_type"].rsplit(".", 1)[-1] for event in mfa_events(events)] == ["delivered", "cancelled", "blocked", "blocked"]
    assert mfa_events(events)[-1]["data"]["reason"] == reason
    assert run.identity_state.mfa["sarah"]["push_count"] == 1


def test_approval_then_containment_does_not_reenable_revoked_path():
    run, _events = runtime()
    run.controller.advance_to(30)
    run.mfa.decide(run.mfa.snapshot()["pending"]["id"], "approve", USER)
    run.submit_action(actor=FACILITATOR, action_id="identity.session.revoke",
                      target=entity("session", "sess-red-01"), idempotency_key="revoke-after-approval")
    run.controller.advance_to(90)
    assert run.mfa.snapshot()["history"][-1]["outcome"] == "blocked"
    assert run.identity_state.sessions["sess-red-01"]["active"] is False


def test_stop_and_reset_discard_old_challenges_and_history():
    run, events = runtime()
    run.controller.advance_to(30)
    old_id = run.mfa.snapshot()["pending"]["id"]
    run.fail_safe_stop("local safety test")
    assert mfa_events(events)[-1]["data"]["reason"] == "fail_safe_stop"
    with pytest.raises(ControllerError, match="running"):
        run.mfa.decide(old_id, "approve", USER)
    with pytest.raises(ValueError, match="new run id"):
        run.reset(new_run_id=run.run_id)
    run.reset(new_run_id="run-mfa-reset")
    assert run.mfa.snapshot()["history"] == []
    assert run.identity_state.mfa["sarah"] == {"push_count": 0, "decision": "pending"}
    run.controller.start()
    run.controller.advance_to(30)
    assert run.mfa.snapshot()["pending"]["id"] != old_id
    with pytest.raises(ControllerError, match="No matching"):
        run.mfa.decide(old_id, "approve", USER)


@pytest.mark.parametrize("decision", [[], {}, True, None, "automatic"])
def test_invalid_decisions_leave_pending_state_unchanged(decision):
    run, events = runtime()
    run.controller.advance_to(30)
    before = run.mfa.snapshot()
    with pytest.raises(ControllerError, match="fields"):
        run.mfa.decide(before["pending"]["id"], decision, USER)
    assert run.mfa.snapshot() == before
    assert len(mfa_events(events)) == 1


def test_wrong_role_and_wrong_challenge_cannot_decide():
    run, events = runtime()
    run.controller.advance_to(30)
    before = run.mfa.snapshot()
    with pytest.raises(ControllerError, match="role"):
        run.mfa.decide(before["pending"]["id"], "approve", entity("participant", "soc", role="soc_analyst"))
    with pytest.raises(ControllerError, match="No matching"):
        run.mfa.decide("mfa-from-another-run", "approve", USER)
    assert run.mfa.snapshot() == before
    assert len(mfa_events(events)) == 1


def test_no_network_access_during_complete_mfa_sequence(monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("synthetic MFA must not access a device or tenant")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    run, events = runtime()
    run.controller.advance_to(30)
    run.mfa.decide(run.mfa.snapshot()["pending"]["id"], "approve", USER)
    run.controller.advance_to(90)
    run.mfa.decide(run.mfa.snapshot()["pending"]["id"], "deny", FACILITATOR)
    run.controller.advance_to(180)
    assert [event["event_type"].rsplit(".", 1)[-1] for event in mfa_events(events)] == ["delivered", "approved", "delivered", "denied", "delivered", "expired"]


def test_competing_human_decisions_resolve_exactly_once():
    run, events = runtime()
    run.controller.advance_to(30)
    challenge_id = run.mfa.snapshot()["pending"]["id"]

    def choose(decision):
        try:
            run.mfa.decide(challenge_id, decision, USER)
            return True
        except ControllerError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(choose, ["approve", "deny"]))
    assert sorted(results) == [False, True]
    assert len(mfa_events(events)) == 2


@pytest.mark.parametrize("field,value", [
    ("timeout_seconds", False), ("timeout_seconds", 0), ("timeout_seconds", 301),
    ("seed", ""), ("seed", None), ("session_id", "unknown-session"),
    ("factor_id", "unknown-factor"), ("identity_id", "not-synthetic"),
])
def test_configuration_fails_closed(field, value):
    run, events = runtime()
    configuration = deepcopy(run.definition.participant_experience["mfa"])
    configuration[field] = value
    with pytest.raises(ValueError):
        ScheduledMfa(exercise_id=run.definition.exercise_id, run_id=run.run_id,
                     configuration=configuration, identity_state=lambda: run.identity_state,
                     run_state=lambda: run.controller.state.value,
                     elapsed=lambda: run.controller.elapsed_seconds,
                     event_sink=events.append, sequence_factory=run.sequencer.next,
                     clock=lambda: NOW, state_lock=run.state_lock)


def test_legacy_actions_cannot_bypass_stateful_challenge_in_exercise_runtime():
    run, events = runtime()
    run.controller.advance_to(30)
    before = run.mfa.snapshot()
    for action_id in ("identity.mfa.challenge.record", "identity.mfa.decision.record"):
        with pytest.raises(ValueError, match="not available"):
            run.submit_action(actor=FACILITATOR, action_id=action_id,
                              target=entity("identity", "sarah"), idempotency_key=action_id)
    assert run.mfa.snapshot() == before
    assert len(mfa_events(events)) == 1
