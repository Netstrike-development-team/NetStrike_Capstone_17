"""Staff-supplied receiver evidence: exact semantic comparison, never live proof."""

from copy import deepcopy
import hashlib
import json
import os

import pytest

from dashboard import telemetry_check as check
from dashboard.auth import PortalPrincipal
from dashboard.service import PortalService
from dashboard.store import PortalStore
from shared.events import EventBuilder, EventContext, entity


EXERCISE = "operation-silent-spider"
RUN = "telemetry-test"


def events():
    builder = EventBuilder(EventContext(EXERCISE, RUN, "facilitator", "probe", "1.0.0"))
    return [builder.build(event_type="exercise.telemetry.test", phase="identity",
                          actor=entity("system", "synthetic"), action="probe",
                          target=entity("scenario_run", RUN), outcome_status="success",
                          visibility=visibility, dry_run=True, message="Synthetic probe")
            for visibility in ("participant", "facilitator", "evaluator")]


def write(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values))
    return path


@pytest.fixture
def inputs(tmp_path):
    values = events()
    return write(tmp_path / "expected", values), write(tmp_path / "observed", values), values


def compare(expected, observed):
    return check.compare(expected, observed, exercise_id=EXERCISE, run_id=RUN)


def test_reordering_and_json_whitespace_do_not_change_semantic_match(inputs):
    expected, observed, values = inputs
    observed.write_text("".join(json.dumps(value, sort_keys=True) + "\n"
                                for value in reversed(values)))
    before = (expected.read_bytes(), observed.read_bytes())
    report = compare(expected, observed)
    assert report["supplied_files_match"] and report["expected_events"] == 3
    assert report["expected_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert report["observed_sha256"] == hashlib.sha256(before[1]).hexdigest()
    assert not report["writes_performed"] and not report["live_splunk_verified"]
    assert not report["external_readiness_verified"]
    assert (expected.read_bytes(), observed.read_bytes()) == before


@pytest.mark.parametrize("fault,key", [("missing", "missing_events"),
    ("duplicate", "duplicate_events"), ("changed", "changed_events"),
    ("unexpected", "unexpected_events")])
def test_each_transport_fault_fails_comparison(inputs, fault, key):
    expected, observed, values = inputs
    if fault == "missing":
        values.pop()
    elif fault == "duplicate":
        values.append(deepcopy(values[0]))
    elif fault == "changed":
        values[0]["message"] = "Receiver changed this message"
    else:
        extra = events()[0]
        extra["sequence"] = 4
        values.append(extra)
    write(observed, values)
    report = compare(expected, observed)
    assert report[key] == 1 and not report["supplied_files_match"]


def test_missing_all_receiver_evidence_is_not_a_vacuous_pass(inputs):
    expected, observed, _ = inputs
    observed.write_bytes(b"")
    report = compare(expected, observed)
    assert report["missing_events"] == 3 and report["sources_with_missing_events"] == 1
    assert not report["supplied_files_match"]


def test_same_file_cannot_be_both_baseline_and_receiver(inputs):
    with pytest.raises(check.TelemetryCheckError, match="separate"):
        compare(inputs[0], inputs[0])


@pytest.mark.parametrize("value", ["", None, True, "a" * 129])
def test_explicit_bounded_scope_required_before_reading(inputs, value):
    with pytest.raises(check.TelemetryCheckError, match="identifiers"):
        check.compare(*inputs[:2], exercise_id=EXERCISE, run_id=value)


def test_crlf_raw_export_is_accepted(inputs):
    expected, observed, _ = inputs
    observed.write_bytes(observed.read_bytes().replace(b"\n", b"\r\n"))
    assert compare(expected, observed)["supplied_files_match"]


@pytest.mark.parametrize("field,value", [("exercise_id", "another-exercise"),
    ("run_id", "after-reset"), ("schema_version", "2.0.0"), ("sequence", 0)])
@pytest.mark.parametrize("side", [0, 1])
def test_mixed_scope_or_invalid_schema_rejected(inputs, side, field, value):
    paths = inputs[:2]
    values = inputs[2]
    values[0][field] = value
    write(paths[side], values)
    with pytest.raises(ValueError):
        compare(*paths)


@pytest.mark.parametrize("bad", [b"", b"\n", b"null\n", b"[]\n", b"{\n",
    b'{"schema_version":"1.0.0","schema_version":"1.0.0"}\n',
    b'{"value":NaN}\n', b"\xff\n", b'{"result":{"_raw":"not canonical"}}\n'])
def test_invalid_baseline_fails_safely(inputs, bad, capsys):
    expected, observed, _ = inputs
    expected.write_bytes(bad)
    assert check.main(["--expected", str(expected), "--observed", str(observed),
                       "--exercise-id", EXERCISE, "--run-id", RUN]) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["status"] == "invalid_input"
    assert str(expected) not in output.err


@pytest.mark.parametrize("mutation", ["duplicate", "gap", "reorder"])
def test_expected_baseline_must_be_contiguous_unique_prefix(inputs, mutation):
    expected, observed, values = inputs
    if mutation == "duplicate":
        values[1] = deepcopy(values[0])
    elif mutation == "gap":
        values[1]["sequence"] = 8
    else:
        values.reverse()
    write(expected, values)
    with pytest.raises(check.TelemetryCheckError):
        compare(expected, observed)


def test_duplicate_changed_copy_cannot_hide_behind_good_first_copy(inputs):
    expected, observed, values = inputs
    altered = deepcopy(values[0])
    altered["message"] = "modified duplicate"
    write(observed, values + [altered])
    report = compare(expected, observed)
    assert report["changed_events"] == report["duplicate_events"] == 1


def test_nested_boolean_and_integer_are_not_equal(inputs):
    expected, observed, values = inputs
    values[0]["data"] = {"observed": True}
    write(expected, values)
    values[0]["data"]["observed"] = 1
    write(observed, values)
    assert compare(expected, observed)["changed_events"] == 1


@pytest.mark.parametrize("side", [0, 1])
def test_secrets_fail_without_leaking_schema_details(inputs, side, capsys):
    paths, values = inputs[:2], inputs[2]
    values[0]["data"] = {"nested": {"authorization": "PRIVATE-SENTINEL"}}
    write(paths[side], values)
    assert check.main(["--expected", str(paths[0]), "--observed", str(paths[1]),
                       "--exercise-id", EXERCISE, "--run-id", RUN]) == 2
    assert "PRIVATE-SENTINEL" not in str(capsys.readouterr())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "missing"])
def test_non_regular_or_linked_inputs_rejected(inputs, tmp_path, kind):
    expected, observed, _ = inputs
    bad = tmp_path / "bad"
    if kind == "symlink":
        bad.symlink_to(expected)
    elif kind == "hardlink":
        os.link(expected, bad)
    elif kind == "directory":
        bad.mkdir()
    elif kind == "fifo":
        os.mkfifo(bad)
    with pytest.raises((OSError, check.TelemetryCheckError)):
        compare(bad, observed)


@pytest.mark.parametrize("limit", ["MAX_FILE_BYTES", "MAX_EVENT_BYTES", "MAX_EVENTS"])
def test_input_bounds(inputs, monkeypatch, limit):
    monkeypatch.setattr(check, limit, 1)
    with pytest.raises(check.TelemetryCheckError):
        compare(*inputs[:2])


def test_input_replacement_during_read_is_rejected(inputs, monkeypatch):
    expected, observed, _ = inputs
    real = check._signature
    calls = 0
    def changed(info):
        nonlocal calls
        calls += 1
        return real(info) if calls < 4 else ("changed",)
    monkeypatch.setattr(check, "_signature", changed)
    with pytest.raises(check.TelemetryCheckError, match="changed"):
        compare(expected, observed)


@pytest.mark.parametrize("matches,code", [(True, 0), (False, 1)])
def test_cli_exit_codes_and_count_only_output(inputs, capsys, matches, code):
    expected, observed, values = inputs
    if not matches:
        write(observed, values[:-1])
    assert check.main(["--expected", str(expected), "--observed", str(observed),
                       "--exercise-id", EXERCISE, "--run-id", RUN]) == code
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out)["supplied_files_match"] == matches
    assert all(item["event_id"] not in output.out for item in values)
    assert RUN not in output.out and str(expected) not in output.out


def test_real_portal_export_and_reset_cannot_mix_evidence(tmp_path):
    store = PortalStore(tmp_path / "portal.sqlite3")
    service = PortalService(store, run_id=RUN)
    staff = PortalPrincipal("staff-test", "facilitator")
    try:
        service.start_run(staff)
        service.run.fail_safe_stop("Stopped synthetic probe")
        before = store.events(EXERCISE, RUN)
        expected = write(tmp_path / "expected", before)
        observed = write(tmp_path / "observed", list(reversed(before)))
        assert compare(expected, observed)["supplied_files_match"]
        service.reset_run(new_run_id="fresh-run", principal=staff)
        service.start_run(staff)
        write(observed, before + store.events(EXERCISE, "fresh-run"))
        with pytest.raises(check.TelemetryCheckError, match="outside"):
            compare(expected, observed)
        # Reset audits created after the saved prefix must be reported as extra,
        # not silently hidden by the checker or treated as an old-run full ledger.
        write(observed, store.events(EXERCISE, RUN))
        assert compare(expected, observed)["unexpected_events"] > 0
    finally:
        store.close()
