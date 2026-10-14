"""Safe synthetic identity capture and retention tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dashboard.identity_audit import IdentityAuditError, IdentityAuditRecorder
from dashboard.store import PortalStore
from shared.events import EventSequencer


NOW = datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)
AUDIT_KEY = b"test-only-identity-audit-key-32-bytes-minimum"


def _payload(**overrides):
    payload = {
        "phase": "identity",
        "synthetic_identity": "sarah",
        "occurred_at": "2026-09-30T19:30:00Z",
        "action": "identity.sign_in.attempt",
        "result": "failure",
        "source_event_id": "source-001",
        "credential_kind": "password",
        "synthetic_credential": "synthetic-secret-not-for-storage",
    }
    payload.update(overrides)
    return payload


def _record(recorder, sequencer, payload, *, run_id="run-audit-test"):
    return recorder.record(
        exercise_id="operation-silent-spider",
        run_id=run_id,
        source_service="simcorp-sso",
        sequence_factory=sequencer.next,
        payload=payload,
    )


def test_raw_credential_never_enters_sqlite_or_canonical_event(tmp_path) -> None:
    database = tmp_path / "portal.sqlite3"
    store = PortalStore(database)
    recorder = IdentityAuditRecorder(store, audit_key=AUDIT_KEY, clock=lambda: NOW)
    sequencer = EventSequencer()
    raw_value = "synthetic-secret-not-for-storage"

    result = _record(recorder, sequencer, _payload())

    assert result["submission_reference"].startswith("hmac-sha256:")
    assert raw_value not in str(result)
    events = store.events("operation-silent-spider", "run-audit-test")
    assert events[0]["event_type"] == "identity.interaction.recorded"
    assert raw_value not in str(events)
    store.close()
    assert raw_value.encode("utf-8") not in database.read_bytes()


def test_timeline_is_queryable_by_run_and_orders_occurrence_time() -> None:
    store = PortalStore()
    recorder = IdentityAuditRecorder(store, audit_key=AUDIT_KEY, clock=lambda: NOW)
    sequencer = EventSequencer()

    _record(
        recorder,
        sequencer,
        _payload(source_event_id="source-later", occurred_at="2026-09-30T19:31:00Z"),
    )
    _record(
        recorder,
        sequencer,
        _payload(source_event_id="source-earlier", occurred_at="2026-09-30T19:29:00Z"),
    )

    timeline = store.identity_audit("operation-silent-spider", "run-audit-test")
    assert [item["source_event_id"] for item in timeline] == [
        "source-earlier",
        "source-later",
    ]
    assert store.identity_audit("operation-silent-spider", "another-run") == []


def test_source_retry_is_idempotent_but_conflicting_retry_is_rejected() -> None:
    store = PortalStore()
    recorder = IdentityAuditRecorder(store, audit_key=AUDIT_KEY, clock=lambda: NOW)
    sequencer = EventSequencer()
    payload = _payload()

    original = _record(recorder, sequencer, payload)
    duplicate = _record(recorder, sequencer, payload)

    assert duplicate["duplicate"] is True
    assert duplicate["audit_id"] == original["audit_id"]
    assert sequencer.sequence == 1
    with pytest.raises(IdentityAuditError, match="different interaction"):
        _record(recorder, sequencer, _payload(result="success"))
    assert len(store.identity_audit("operation-silent-spider", "run-audit-test")) == 1


@pytest.mark.parametrize(
    "payload,error",
    [
        (_payload(password="unexpected"), "unsupported fields"),
        (_payload(credential_kind=None), "must be supplied together"),
        (_payload(action="Sign In"), "event-name format"),
        (_payload(result="compromised"), "result is not supported"),
    ],
)
def test_schema_validation_rejects_unsafe_or_malformed_input(payload, error) -> None:
    store = PortalStore()
    recorder = IdentityAuditRecorder(store, audit_key=AUDIT_KEY, clock=lambda: NOW)

    with pytest.raises(IdentityAuditError, match=error):
        _record(recorder, EventSequencer(), payload)
    assert store.identity_audit("operation-silent-spider", "run-audit-test") == []


def test_cleanup_is_run_scoped_and_reaches_empty_baseline() -> None:
    store = PortalStore()
    recorder = IdentityAuditRecorder(store, audit_key=AUDIT_KEY, clock=lambda: NOW)
    _record(recorder, EventSequencer(), _payload(), run_id="run-one")
    _record(
        recorder,
        EventSequencer(),
        _payload(source_event_id="source-002"),
        run_id="run-two",
    )

    assert store.delete_identity_audit("operation-silent-spider", "run-one") == 1
    assert store.identity_audit("operation-silent-spider", "run-one") == []
    assert len(store.identity_audit("operation-silent-spider", "run-two")) == 1
    assert store.delete_identity_audit("operation-silent-spider", "missing") == 0
