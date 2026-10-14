"""SQLite portal persistence tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dashboard.store import PortalStore
from shared.events import EventBuilder, EventContext, entity


NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


def _event(visibility="participant"):
    return EventBuilder(
        EventContext(
            exercise_id="operation-silent-spider",
            run_id="run-store-test",
            source_kind="test",
            source_component="portal-store-test",
            producer_version="1.0.0",
        ),
        clock=lambda: NOW,
    ).build(
        event_type="test.event.created",
        phase="control",
        actor=entity("system", "test"),
        action="test.create",
        target=entity("fixture", "one"),
        outcome_status="success",
        message="Created test event",
        visibility=visibility,
        dry_run=True,
        data={"password": "must-redact"},
    )


def test_store_redacts_events_and_filters_visibility() -> None:
    store = PortalStore()
    participant_event = _event()
    facilitator_event = _event("facilitator")
    facilitator_event["event_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    facilitator_event["sequence"] = 2

    store.append_event(participant_event)
    store.append_event(facilitator_event)

    visible = store.events(
        "operation-silent-spider",
        "run-store-test",
        visibilities=frozenset({"participant"}),
    )
    assert len(visible) == 1
    assert visible[0]["data"]["password"] == "[REDACTED]"
    assert len(store.events("operation-silent-spider", "run-store-test")) == 2


def test_store_persists_submission_and_result() -> None:
    store = PortalStore()

    submission_id = store.save_submission(
        exercise_id="operation-silent-spider",
        run_id="run-store-test",
        actor_id="learner-01",
        submission_type="DP1",
        payload={"classification": "likely account compromise"},
        result={"passed": True},
    )

    submissions = store.submissions("run-store-test")
    assert submission_id == 1
    assert submissions[0]["actor_id"] == "learner-01"
    assert submissions[0]["result"] == {"passed": True}
