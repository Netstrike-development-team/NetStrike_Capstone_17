from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shared.events import (
    DEFAULT_SCHEMA_PATH,
    EventBuilder,
    EventCompatibilityError,
    EventContext,
    EventContractError,
    EventLedger,
    EventLedgerError,
    EventValidationError,
    EventValidator,
    correlation_key,
    entity,
    load_schema,
)
from shared.legacy_events import migrate_legacy_event

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
FIXTURES = DEFAULT_SCHEMA_PATH.parent / "fixtures" / "events"


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_builder(*, start_sequence: int = 0, clock=lambda: NOW) -> EventBuilder:
    event_ids = iter(
        [
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        ]
    )
    return EventBuilder(
        EventContext(
            exercise_id="silent-spider",
            run_id="run-test-001",
            source_kind="test",
            source_component="contract-test",
            producer_version="1.0.0",
            source_host="TEST01",
        ),
        start_sequence=start_sequence,
        clock=clock,
        event_id_factory=lambda: next(event_ids),
    )


def build_event(builder: EventBuilder, **overrides) -> dict:
    values = {
        "event_type": "test.event.created",
        "phase": "control",
        "actor": entity("system", "contract-test"),
        "action": "event.create",
        "target": entity("fixture", "event-001"),
        "outcome_status": "success",
        "message": "Created a synthetic contract-test event",
        "dry_run": True,
        "safety_controls": ("unit-test",),
        "data": {"synthetic": True},
    }
    values.update(overrides)
    return builder.build(**values)


def test_schema_is_valid_draft_2020_12():
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_compatibility_entry_point_references_v1():
    pointer = json.loads(
        (DEFAULT_SCHEMA_PATH.parent / "event.json").read_text(encoding="utf-8")
    )
    assert pointer["$ref"] == "event.v1.json"


@pytest.mark.parametrize("fixture_path", sorted((FIXTURES / "valid").glob("*.json")))
def test_valid_fixtures_satisfy_contract(fixture_path: Path):
    EventValidator().validate(load_fixture(fixture_path))


@pytest.mark.parametrize("fixture_path", sorted((FIXTURES / "invalid").glob("*.json")))
def test_invalid_fixtures_are_rejected(fixture_path: Path):
    with pytest.raises((EventValidationError, EventCompatibilityError)):
        EventValidator().validate(load_fixture(fixture_path))


def test_builder_emits_valid_correlated_event_and_monotonic_sequence():
    builder = make_builder()
    first = build_event(builder)
    second = build_event(
        builder,
        correlation_ids=(first["event_id"],),
        objective_ids=("LO2", "LO1", "LO2"),
        checkpoint_id="DP1",
    )

    assert correlation_key(first) == ("silent-spider", "run-test-001")
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["correlation_ids"] == [first["event_id"]]
    assert second["objective_ids"] == ["LO1", "LO2"]
    EventValidator().validate(second)


def test_builder_rejects_naive_timestamps():
    builder = make_builder()
    with pytest.raises(EventContractError, match="timezone-aware"):
        build_event(builder, timestamp=datetime(2026, 9, 16, 14, 0))


def test_builder_requires_complete_attack_mapping():
    builder = make_builder()
    with pytest.raises(EventContractError, match="must be supplied together"):
        build_event(builder, attack_technique_id="T1078")


def test_builder_only_advances_sequence_after_successful_validation():
    builder = make_builder()

    with pytest.raises(EventValidationError):
        build_event(builder, event_id="not-a-uuid")

    assert builder.sequence == 0
    assert build_event(builder)["sequence"] == 1


def test_recursive_redaction_happens_before_publish():
    event = build_event(
        make_builder(),
        data={
            "username": "synthetic-user",
            "password": "do-not-store",
            "nested": {
                "api_key": "do-not-store",
                "items": [{"sessionToken": "do-not-store"}],
            },
        },
    )

    assert event["data"]["username"] == "synthetic-user"
    assert event["data"]["password"] == "[REDACTED]"
    assert event["data"]["nested"]["api_key"] == "[REDACTED]"
    assert event["data"]["nested"]["items"][0]["sessionToken"] == "[REDACTED]"


def test_ledger_redacts_externally_constructed_events(tmp_path: Path):
    event = build_event(make_builder())
    event["data"]["client_secret"] = "do-not-store"
    ledger = EventLedger(tmp_path / "events.jsonl", clock=lambda: NOW)

    stored = ledger.append(event)
    persisted = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))

    assert stored["data"]["client_secret"] == "[REDACTED]"
    assert persisted == stored


def test_ledger_rejects_duplicate_event_ids(tmp_path: Path):
    event = build_event(make_builder())
    ledger = EventLedger(tmp_path / "events.jsonl", clock=lambda: NOW)
    ledger.append(event)

    with pytest.raises(EventLedgerError, match="duplicate event_id"):
        ledger.append(event)


def test_ledger_rejects_out_of_order_sequence_for_same_run(tmp_path: Path):
    builder = make_builder(start_sequence=1)
    later = build_event(builder)
    earlier = deepcopy(later)
    earlier["event_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    earlier["sequence"] = 1
    ledger = EventLedger(tmp_path / "events.jsonl", clock=lambda: NOW)
    ledger.append(later)

    with pytest.raises(EventLedgerError, match="out-of-order sequence"):
        ledger.append(earlier)


def test_ledger_allows_independent_sequences_for_different_runs(tmp_path: Path):
    first = build_event(make_builder())
    second = deepcopy(first)
    second["event_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    second["run_id"] = "run-test-002"
    ledger = EventLedger(tmp_path / "events.jsonl", clock=lambda: NOW)

    ledger.append(first)
    ledger.append(second)

    assert ledger.event_count == 2


def test_ledger_rejects_timestamp_beyond_future_skew(tmp_path: Path):
    event = build_event(
        make_builder(clock=lambda: NOW + timedelta(minutes=6)),
    )
    ledger = EventLedger(
        tmp_path / "events.jsonl",
        clock=lambda: NOW,
        max_future_skew=timedelta(minutes=5),
    )

    with pytest.raises(EventLedgerError, match="in the future"):
        ledger.append(event)


def test_ledger_reload_preserves_duplicate_and_order_guards(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    builder = make_builder()
    first = build_event(builder)
    second = build_event(builder)
    EventLedger(path, clock=lambda: NOW).append(first)

    reloaded = EventLedger(path, clock=lambda: NOW)
    assert reloaded.event_count == 1
    with pytest.raises(EventLedgerError, match="duplicate event_id"):
        reloaded.append(first)

    reloaded.append(second)
    assert reloaded.event_count == 2


def test_consumer_accepts_compatible_minor_but_rejects_new_major():
    event = build_event(make_builder())
    compatible = deepcopy(event)
    compatible["schema_version"] = "1.7.2"
    EventValidator().validate(compatible)

    incompatible = deepcopy(event)
    incompatible["schema_version"] = "2.0.0"
    with pytest.raises(EventCompatibilityError, match="unsupported event schema major 2"):
        EventValidator().validate(incompatible)


def test_legacy_adapter_maps_fields_phase_and_redacts_secrets():
    legacy = {
        "event_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "timestamp": "2026-09-16T14:00:00+00:00",
        "phase": 6,
        "technique_id": "T1530",
        "tactic": "collection",
        "description": "Listed synthetic mock-cloud objects",
        "source_module": "06-cloud-exfil",
        "flag_triggered": "FLAG_6_COMPLETE",
        "raw_data": {"record_count": 5, "access_token": "do-not-store"},
    }
    context = EventContext(
        exercise_id="silent-spider",
        run_id="run-migration-001",
        source_kind="module",
        source_component="legacy-adapter",
        producer_version="1.0.0",
    )

    migrated = migrate_legacy_event(legacy, context=context, sequence=4)

    assert migrated["event_id"] == legacy["event_id"]
    assert migrated["phase"] == "cloud"
    assert migrated["sequence"] == 4
    assert migrated["provenance"]["source_event_id"] == legacy["event_id"]
    assert migrated["data"]["raw_data"]["access_token"] == "[REDACTED]"
    assert migrated["attack"] == {"technique_id": "T1530", "tactic": "collection"}
    EventValidator().validate(migrated)


def test_legacy_phase_zero_becomes_internal_control_error():
    context = EventContext(
        exercise_id="silent-spider",
        run_id="run-migration-002",
        source_kind="module",
        source_component="legacy-adapter",
        producer_version="1.0.0",
    )
    migrated = migrate_legacy_event(
        {
            "phase": 0,
            "tactic": "error",
            "description": "Legacy module error",
            "source_module": "07-ransomware-sim",
            "raw_data": {"error": "synthetic failure"},
        },
        context=context,
        sequence=1,
    )

    assert migrated["phase"] == "control"
    assert migrated["outcome"]["status"] == "error"
    assert migrated["visibility"] == "internal"
    assert migrated["severity"] == "high"
