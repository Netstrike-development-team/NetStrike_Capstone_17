"""Read-only learner-audit/raw-export comparison; never live Splunk acceptance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

from .learner_audit import validate_audit
from .telemetry_check import _canonical, _constant, _pairs, _read

MAX_EVENT_BYTES = 256 * 1024
MAX_EVENTS = 10000
SCOPE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ERROR_CODES = frozenset({"event_limit_exceeded", "empty_event_line", "invalid_raw_jsonl",
    "learner_contract_violation", "outside_selected_scope", "invalid_comparison_scope",
    "unsafe_or_unavailable_input", "separate_files_required", "duplicate_baseline_event", "empty_baseline"})


class LearnerCheckError(ValueError):
    """Fixed diagnostic code only; no raw evidence or path in CLI receipts."""


def _events(content, exercise_id, run_id):
    stream = io.BytesIO(content)
    count = 0
    while chunk := stream.readline(MAX_EVENT_BYTES + 3):
        count += 1
        line = chunk.removesuffix(b"\n").removesuffix(b"\r")
        if count > MAX_EVENTS or len(line) > MAX_EVENT_BYTES:
            raise LearnerCheckError("event_limit_exceeded")
        if not line:
            raise LearnerCheckError("empty_event_line")
        try:
            event = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise LearnerCheckError("invalid_raw_jsonl") from None
        try:
            validate_audit(event)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise LearnerCheckError("learner_contract_violation") from None
        if event["exercise_id"] != exercise_id or event["run_id"] != run_id:
            raise LearnerCheckError("outside_selected_scope")
        yield event, _canonical(event)


def compare(expected, observed, *, exercise_id, run_id):
    """Compare supplied event content by ID; filtered audits have no sequence."""
    if any(not isinstance(value, str) or SCOPE_ID.fullmatch(value) is None for value in (exercise_id, run_id)):
        raise LearnerCheckError("invalid_comparison_scope")
    try:
        expected_bytes, observed_bytes = _read(expected), _read(observed)
        same = os.path.samefile(expected, observed)
    except (OSError, ValueError):
        raise LearnerCheckError("unsafe_or_unavailable_input") from None
    if same:
        raise LearnerCheckError("separate_files_required")
    baseline, service_by_id = {}, {}
    for event, encoded in _events(expected_bytes, exercise_id, run_id):
        key = event["event_id"]
        if key in baseline:
            raise LearnerCheckError("duplicate_baseline_event")
        baseline[key] = encoded
        service_by_id[key] = event["service"]
    if not baseline:
        raise LearnerCheckError("empty_baseline")

    seen, changed = set(), set()
    observed_count = duplicates = unexpected = 0
    for event, encoded in _events(observed_bytes, exercise_id, run_id):
        key = event["event_id"]
        observed_count += 1
        if key in seen:
            duplicates += 1
        seen.add(key)
        if key not in baseline:
            unexpected += 1
        elif encoded != baseline[key]:
            changed.add(key)
    missing = set(baseline) - seen
    matches = not (missing or changed or duplicates or unexpected)
    return {"version": "1.0.0", "scope": "supplied_learner_raw_export_comparison",
            "schema_id": "netstrike.learner-audit.v1",
            "status": "match" if matches else "mismatch", "supplied_files_match": matches,
            "expected_events": len(baseline), "observed_events": observed_count,
            "matched_events": len(baseline) - len(missing) - len(changed),
            "missing_events": len(missing), "changed_events": len(changed),
            "duplicate_events": duplicates, "unexpected_events": unexpected,
            "expected_services": len(set(service_by_id.values())),
            "services_with_missing_events": len({service_by_id[key] for key in missing}),
            "expected_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "observed_sha256": hashlib.sha256(observed_bytes).hexdigest(),
            "writes_performed": False, "live_splunk_verified": False,
            "participant_access_verified": False, "external_readiness_verified": False}


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "Invalid learner comparison arguments. Use --help.\n")


def main(argv=None):
    """Counts/digests only: 0 match, 1 mismatch, 2 invalid or unsafe input."""
    parser = SafeParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--exercise-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        report = compare(args.expected, args.observed, exercise_id=args.exercise_id, run_id=args.run_id)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        code = str(error) if isinstance(error, LearnerCheckError) and str(error) in ERROR_CODES else "invalid_input"
        print(json.dumps({"scope": "supplied_learner_raw_export_comparison", "status": "invalid_input",
                          "code": code, "supplied_files_match": False, "writes_performed": False,
                          "live_splunk_verified": False, "participant_access_verified": False,
                          "external_readiness_verified": False}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["supplied_files_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
