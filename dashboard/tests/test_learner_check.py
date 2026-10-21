"""Strict learner raw-event comparison, safe receipts and no mutation/fallback."""

from copy import deepcopy
import hashlib
import json
import os
import socket
import sqlite3
import subprocess

import pytest

from dashboard import learner_check as check, telemetry_check
from dashboard.learner_audit import project, validate_audit
from shared.events import EventBuilder, EventContext, entity

EXERCISE, RUN = "operation-silent-spider", "learner-comparison-test"


def write(path, records):
    path.write_text("".join(json.dumps(event) + "\n" for event in records), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path):
    builder = EventBuilder(EventContext(EXERCISE, RUN, "module", "helpdesk-simulator", "1.0.0"))
    records = [project(builder.build(event_type="helpdesk.identity_reset.completed", phase="identity",
        actor=entity("helpdesk_agent", "tyler"), action="helpdesk.identity_reset",
        target=entity("identity", "sarah"), outcome_status="success", visibility="participant",
        message="PRIVATE PROSE NEVER EXPORTED", dry_run=True,
        data={"ticket_id": f"HD-{index}", "callback_verified": False})) for index in range(3)]
    return write(tmp_path / "expected.jsonl", records), write(tmp_path / "observed.jsonl", records), records


def compare(expected, observed):
    return check.compare(expected, observed, exercise_id=EXERCISE, run_id=RUN)


def cli(expected, observed):
    return check.main(["--expected", str(expected), "--observed", str(observed), "--exercise-id", EXERCISE, "--run-id", RUN])


def test_order_whitespace_and_crlf_do_not_change_match(inputs):
    expected, observed, records = inputs
    observed.write_bytes("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\r\n" for event in reversed(records)).encode())
    before = expected.read_bytes(), observed.read_bytes()
    result = compare(expected, observed)
    assert result["supplied_files_match"] and result["matched_events"] == 3
    assert result["expected_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert result["observed_sha256"] == hashlib.sha256(before[1]).hexdigest()
    assert (expected.read_bytes(), observed.read_bytes()) == before
    assert not any(result[name] for name in ("writes_performed", "live_splunk_verified", "participant_access_verified",
                                           "indexed_event_boundaries_verified", "external_readiness_verified"))


@pytest.mark.parametrize("fault,key", [("missing", "missing_events"), ("duplicate", "duplicate_events"),
    ("changed", "changed_events"), ("unexpected", "unexpected_events"), ("all-missing", "missing_events")])
def test_transport_faults_fail_without_changing_evidence(inputs, fault, key):
    expected, observed, records = inputs
    if fault == "missing":
        records.pop()
    elif fault == "duplicate":
        records.append(deepcopy(records[0]))
    elif fault == "changed":
        records[0]["facts"]["ticket_id"] = "HD-changed"
    elif fault == "unexpected":
        extra = deepcopy(records[0])
        extra["event_id"] = "11223344-5566-4788-99aa-bbccddeeff00"
        records.append(extra)
    else:
        records = []
    write(observed, records)
    before = expected.read_bytes(), observed.read_bytes()
    report = compare(expected, observed)
    assert report["status"] == "mismatch" and report[key] == (3 if fault == "all-missing" else 1)
    assert not report["supplied_files_match"] and (expected.read_bytes(), observed.read_bytes()) == before


def test_changed_duplicate_cannot_hide_behind_original(inputs):
    expected, observed, records = inputs
    changed = deepcopy(records[0])
    changed["facts"]["callback_verified"] = True
    write(observed, records + [changed])
    result = compare(expected, observed)
    assert result["duplicate_events"] == result["changed_events"] == 1
    assert result["matched_events"] == 2


def test_filtered_baseline_needs_no_sequence_or_order(inputs):
    expected, observed, records = inputs
    write(expected, list(reversed(records)))
    assert compare(expected, observed)["supplied_files_match"]


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("field,value,code", [
    ("run_id", "after-reset", "outside_selected_scope"),
    ("exercise_id", "different-exercise", "outside_selected_scope"),
    ("schema_version", "2.0.0", "learner_contract_violation"),
    ("schema_id", "netstrike.event.v1", "learner_contract_violation"),
    ("event_type", "scenario.checkpoint.resolved", "learner_contract_violation"),
    ("service", "unreviewed-service", "learner_contract_violation"),
    ("message", "PRIVATE SENTINEL", "learner_contract_violation"),
    ("sequence", 1, "learner_contract_violation"),
])
def test_wrong_scope_private_or_incompatible_content_is_refused(inputs, side, field, value, code, capsys):
    paths, records = inputs[:2], inputs[2]
    records[0][field] = value
    write(paths[side], records)
    assert cli(*paths) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["code"] == code
    assert "PRIVATE" not in output.err and str(paths[side]) not in output.err


@pytest.mark.parametrize("change", ["private-fact", "wrong-service-fact", "unpaired-actor", "bool-as-number", "unknown-operation"])
def test_strict_projection_shape_not_just_generic_schema(inputs, change):
    event = deepcopy(inputs[2][0])
    if change == "private-fact":
        event["facts"]["answer"] = "PRIVATE"
    elif change == "wrong-service-fact":
        event["facts"]["confirmed_count"] = 25
    elif change == "unpaired-actor":
        event.pop("actor_type")
    elif change == "bool-as-number":
        event["facts"]["callback_verified"] = 0
    else:
        event["event_type"] = "identity.unreviewed"
    with pytest.raises(ValueError):
        validate_audit(event)


@pytest.mark.parametrize("bad", [b"\n", b"null\n", b"[]\n", b"{\n", b"\xff\n", b'"PRIVATE"\n',
    b'{"facts":{},"facts":{}}\n', b'{"facts":{"count":NaN}}\n',
    b'{"result":{"_raw":"PRIVATE"}}\n', b'event_id,facts\n', b'\xef\xbb\xbf{}\n'])
def test_malformed_or_wrapped_export_has_no_fallback(inputs, bad, capsys):
    expected, observed, _records = inputs
    observed.write_bytes(bad)
    assert cli(expected, observed) == 2
    output = capsys.readouterr()
    assert not output.out and "PRIVATE" not in output.err


@pytest.mark.parametrize("duplicate", [False, True])
def test_empty_or_duplicate_baseline_cannot_pass(inputs, duplicate):
    expected, observed, records = inputs
    write(expected, records + [records[0]] if duplicate else [])
    with pytest.raises(check.LearnerCheckError, match="duplicate_baseline_event" if duplicate else "empty_baseline"):
        compare(expected, observed)


@pytest.mark.parametrize("value", [None, True, "", "x" * 129, "space in scope"])
def test_scope_is_required_before_file_reads(inputs, monkeypatch, value):
    def forbidden(*_args):
        raise AssertionError("invalid scope read an input")
    monkeypatch.setattr(check, "_read", forbidden)
    with pytest.raises(check.LearnerCheckError, match="invalid_comparison_scope"):
        check.compare(*inputs[:2], exercise_id=EXERCISE, run_id=value)


def test_same_file_is_not_independent_evidence(inputs):
    with pytest.raises(check.LearnerCheckError, match="separate_files"):
        compare(inputs[0], inputs[0])


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "missing"])
def test_linked_or_special_files_refused_without_blocking(inputs, tmp_path, kind):
    expected, observed, _records = inputs
    bad = tmp_path / "bad"
    if kind == "symlink":
        bad.symlink_to(expected)
    elif kind == "hardlink":
        os.link(expected, bad)
    elif kind == "directory":
        bad.mkdir()
    elif kind == "fifo":
        os.mkfifo(bad)
    with pytest.raises(check.LearnerCheckError, match="unsafe_or_unavailable"):
        compare(bad, observed)


@pytest.mark.parametrize("limit", ["MAX_FILE_BYTES", "MAX_EVENT_BYTES", "MAX_EVENTS"])
def test_all_input_limits_refuse_without_partial_pass(inputs, monkeypatch, limit):
    monkeypatch.setattr(telemetry_check if limit == "MAX_FILE_BYTES" else check, limit, 1)
    with pytest.raises(check.LearnerCheckError):
        compare(*inputs[:2])


def test_input_changed_while_reading_is_refused(inputs, monkeypatch):
    original, calls = telemetry_check._signature, []
    def replaced(info):
        calls.append(True)
        return original(info) if len(calls) < 4 else ("changed",)
    monkeypatch.setattr(telemetry_check, "_signature", replaced)
    with pytest.raises(check.LearnerCheckError, match="unsafe_or_unavailable"):
        compare(*inputs[:2])


@pytest.mark.parametrize("match", [True, False])
def test_cli_codes_and_count_only_receipt(inputs, match, capsys):
    expected, observed, records = inputs
    if not match:
        write(observed, records[:-1])
    assert cli(expected, observed) == (0 if match else 1)
    captured = capsys.readouterr()
    assert not captured.err and json.loads(captured.out)["supplied_files_match"] == match
    for value in [RUN, str(expected), *(r["event_id"] for r in records), "HD-0", "tyler"]:
        assert value not in captured.out


def test_no_network_database_subprocess_or_file_writes(inputs, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("comparison attempted mutation or external activity")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(type(inputs[0]), "write_text", forbidden)
    assert compare(*inputs[:2])["supplied_files_match"]


def test_invalid_cli_arguments_never_echo_pasted_private_text(capsys):
    with pytest.raises(SystemExit) as failure:
        check.main(["--PRIVATE-pasted-credential"])
    assert failure.value.code == 2 and "PRIVATE" not in capsys.readouterr().err


def test_unexpected_exception_text_cannot_become_a_diagnostic(inputs, monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise check.LearnerCheckError("PRIVATE accidental provider detail")
    monkeypatch.setattr(check, "compare", fail)
    assert cli(*inputs[:2]) == 2
    captured = capsys.readouterr()
    assert "PRIVATE" not in captured.err and json.loads(captured.err)["code"] == "invalid_input"
