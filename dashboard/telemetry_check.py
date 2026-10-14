"""Read-only comparison of canonical evidence and a staff-supplied raw export."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys

from shared.events import EventContractError, EventValidator, redact_sensitive

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_EVENT_BYTES = 256 * 1024
MAX_EVENTS = 10_000


class TelemetryCheckError(ValueError):
    """Invalid evidence input; diagnostics must not include its contents."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TelemetryCheckError("duplicate JSON field")
        result[key] = value
    return result


def _constant(_value):
    raise TelemetryCheckError("non-finite JSON number")


def _canonical(event):
    # Serialized equality distinguishes bool/int and nested values, unlike dict ==.
    return json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path):
    # Parents are caller-trusted staging locations; do not follow a linked leaf
    # or block on a FIFO/device. No input or destination is created or modified.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > MAX_FILE_BYTES):
            raise TelemetryCheckError("unsafe or oversized input file")
        content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise TelemetryCheckError("oversized input file")
        if (_signature(before) != _signature(os.fstat(stream.fileno()))
                or _signature(before) != _signature(Path(path).lstat())):
            raise TelemetryCheckError("input changed while reading")
    return content


def _events(content, validator, exercise_id, run_id):
    stream = io.BytesIO(content)
    count = 0
    while chunk := stream.readline(MAX_EVENT_BYTES + 3):
        count += 1
        if count > MAX_EVENTS:
            raise TelemetryCheckError("too many events")
        line = chunk.removesuffix(b"\n").removesuffix(b"\r")
        if not line or len(line) > MAX_EVENT_BYTES:
            raise TelemetryCheckError("empty or oversized event line")
        event = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
        if not isinstance(event, dict):
            raise TelemetryCheckError("expected a canonical event object")
        validator.validate(event)
        if event["exercise_id"] != exercise_id or event["run_id"] != run_id:
            raise TelemetryCheckError("event outside selected exercise/run")
        encoded = _canonical(event)
        if encoded != _canonical(redact_sensitive(event)):
            raise TelemetryCheckError("unredacted event input")
        yield event, encoded


def compare(expected, observed, *, exercise_id, run_id):  # pylint: disable=too-many-locals
    """Compare only supplied files; never assert receiver or environment readiness."""
    if any(not isinstance(value, str) or not value or len(value) > 128
           for value in (exercise_id, run_id)):
        raise TelemetryCheckError("explicit exercise/run identifiers required")
    validator = EventValidator()
    expected_bytes, observed_bytes = _read(expected), _read(observed)
    if os.path.samefile(expected, observed):
        raise TelemetryCheckError("baseline and receiver export must be separate files")
    baseline, source_by_id = {}, {}
    for event, encoded in _events(expected_bytes, validator, exercise_id, run_id):
        if event["event_id"] in baseline or event["sequence"] != len(baseline) + 1:
            raise TelemetryCheckError("baseline must have unique contiguous events from one")
        baseline[event["event_id"]] = encoded
        source_by_id[event["event_id"]] = event["source"]["component"]
    if not baseline:
        raise TelemetryCheckError("empty baseline cannot verify evidence")

    seen, changed = set(), set()
    observed_count = duplicates = unexpected = 0
    for event, encoded in _events(observed_bytes, validator, exercise_id, run_id):
        event_id = event["event_id"]
        observed_count += 1
        if event_id in seen:
            duplicates += 1
        seen.add(event_id)
        if event_id not in baseline:
            unexpected += 1
        elif baseline[event_id] != encoded:
            changed.add(event_id)
    missing = set(baseline) - seen
    matches = not (missing or changed or duplicates or unexpected)
    return {
        "version": "1.0.0",
        "scope": "supplied_staff_raw_export_comparison",
        "status": "match" if matches else "mismatch",
        "supplied_files_match": matches,
        "expected_events": len(baseline),
        "observed_events": observed_count,
        "missing_events": len(missing),
        "changed_events": len(changed),
        "duplicate_events": duplicates,
        "unexpected_events": unexpected,
        "expected_sources": len(set(source_by_id.values())),
        "sources_with_missing_events": len({source_by_id[key] for key in missing}),
        "expected_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "observed_sha256": hashlib.sha256(observed_bytes).hexdigest(),
        "writes_performed": False,
        "live_splunk_verified": False,
        "external_readiness_verified": False,
    }


def main(argv=None):
    """Emit safe count/digest receipts: 0 match, 1 mismatch, 2 invalid inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--exercise-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(args.expected, args.observed,
                         exercise_id=args.exercise_id, run_id=args.run_id)
    except (OSError, ValueError, TypeError, RecursionError, EventContractError):
        # Schema/JSON/OS exceptions can contain raw evidence, secrets or paths.
        print(json.dumps({"status": "invalid_input", "supplied_files_match": False,
                          "writes_performed": False, "live_splunk_verified": False,
                          "external_readiness_verified": False}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["supplied_files_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
