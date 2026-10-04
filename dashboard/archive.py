"""Validated immutable staff review snapshots, not backups or signed evidence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from orchestrator.aar import build_report
from shared.events import EventValidator, redact_sensitive

VERSION = "1.0.0"
MAX_BYTES = 20 * 1024 * 1024
BOUNDARY = "terminal_review_snapshot_before_archive_audit"
REASONS = frozenset({"staff_capture", "application_reset"})
ROLES = frozenset({"evaluator", "facilitator", "technical_operator", "system"})


def archive_id(value: str) -> str:
    """Use canonical UUIDs as opaque archive identifiers, never filesystem paths."""
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid review archive id") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("invalid review archive id")
    return value


def encode_bundle(bundle) -> str:
    """Apply existing AAR validation and reject unsafe/oversized stored inputs."""
    report = build_report(bundle)
    if [event["sequence"] for event in bundle["events"]] != list(
        range(1, len(bundle["events"]) + 1)
    ):
        raise ValueError("review archive requires a complete event prefix")
    if report["run_state"] not in {"stopped", "completed"}:
        raise ValueError("review archive requires stopped or completed play")
    if redact_sensitive(bundle) != bundle:
        raise ValueError("review archive contains unredacted sensitive fields")
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("review archive exceeds the offline review limit")
    return encoded


# Enumerated correlation checks at one untrusted persistence boundary stay explicit.
# pylint: disable=too-many-boolean-expressions
def metadata(bundle, audit) -> dict:
    """Derive metadata only from the validated bundle and its canonical audit."""
    encode_bundle(bundle)
    EventValidator().validate(audit)
    report = build_report(bundle)
    result = {
        "archive_id": archive_id(audit["target"]["id"]),
        "archive_version": VERSION,
        "captured_at": audit["timestamp"],
        "capture_reason": audit["data"]["capture_reason"],
        "capture_boundary": BOUNDARY,
        "captured_by": {
            "actor_id": audit["actor"]["id"],
            "role": audit["actor"]["role"],
        },
        "exercise_id": bundle["exercise_id"],
        "run_id": bundle["run_id"],
        "scenario_id": bundle["scenario_id"],
        "run_state": bundle["run_state"],
        "bundle_sha256": bundle["content_sha256"],
        "event_count": len(bundle["events"]),
        "submission_count": len(bundle["submissions"]),
        "last_sequence": bundle["events"][-1]["sequence"] if bundle["events"] else 0,
        "review_status": report["status"],
        "reviewed_objectives": report["reviewed_objectives"],
        "audit_event_id": audit["event_id"],
    }
    expected_data = {
        "archive_id": result["archive_id"],
        "bundle_sha256": result["bundle_sha256"],
        "last_sequence": result["last_sequence"],
        "capture_reason": result["capture_reason"],
    }
    if (
        result["capture_reason"] not in REASONS
        or result["captured_by"]["role"] not in ROLES
        or not isinstance(result["captured_by"]["actor_id"], str)
        or not 1 <= len(result["captured_by"]["actor_id"]) <= 256
        or audit["event_type"] != "evaluation.archive.created"
        or audit["action"] != "evaluation.archive.capture"
        or audit["target"]["type"] != "review_archive"
        or audit["exercise_id"] != bundle["exercise_id"]
        or audit["run_id"] != bundle["run_id"]
        or audit["sequence"] != result["last_sequence"] + 1
        or audit["visibility"] != "evaluator"
        or audit["outcome"]["status"] != "success"
        or audit["data"] != expected_data
        or any(item["event_id"] == audit["event_id"] for item in bundle["events"])
    ):
        raise ValueError("review archive audit correlation is invalid")
    if result["capture_reason"] == "staff_capture" and result["captured_by"][
        "role"
    ] not in {
        "evaluator",
        "facilitator",
    }:
        raise ValueError("review archive capture requires a review role")
    if result["capture_reason"] == "application_reset" and result["captured_by"][
        "role"
    ] not in {
        "facilitator",
        "technical_operator",
        "system",
    }:
        raise ValueError("review archive reset capture requires a control role")
    datetime.fromisoformat(result["captured_at"].replace("Z", "+00:00"))
    return result


def validate_snapshot(record, bundle, audit) -> dict:
    """Recompute metadata and report; checksum equality alone is not sufficient."""
    try:
        if record != metadata(bundle, audit):
            raise ValueError("review archive metadata is inconsistent")
        return build_report(bundle)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("review archive validation failed") from exc
