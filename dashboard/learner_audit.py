"""Explicit SimCorp audit projection, never a copy of the canonical staff ledger."""

from __future__ import annotations

import re
import json
from functools import lru_cache
from pathlib import Path
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from shared.events import EventValidator, redact_sensitive

VERSION = "1.0.0"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
ENTITY_TYPES = frozenset({"identity", "helpdesk_agent", "session", "service", "host",
                          "mfa_factor", "directory", "directory_account", "directory_group",
                          "cloud_principal", "cloud_bucket", "process", "file_set"})


def _rule(producer, service, operation, *fields):
    return producer, service, operation, frozenset(fields)


# No prefixes/wildcards: new producer/event types are private until reviewed.
RULES = {
    "identity.fake_sso.submitted": _rule("identity-simulator", "simcorp-access", "web.form.submitted", "source_ip", "landing_id"),
    "helpdesk.identity_reset.completed": _rule("helpdesk-simulator", "simcorp-helpdesk", "identity.reset.completed", "ticket_id", "callback_verified", "caller_employee_id"),
    "identity.authentication.succeeded": _rule("identity-simulator", "simcorp-identity", "authentication.attempt", "source_ip", "factor_id", "host"),
    "identity.authentication.blocked": _rule("identity-simulator", "simcorp-identity", "authentication.attempt", "source_ip", "factor_id", "host"),
    "identity.factor.registered": _rule("identity-simulator", "simcorp-identity", "mfa.factor.enrolled", "identity_id", "source_ip"),
    "identity.session.created": _rule("identity-simulator", "simcorp-identity", "session.created", "source_ip"),
    "identity.mfa.challenge.delivered": _rule("scheduled-mfa", "simcorp-identity", "mfa.challenge.delivered", "challenge_id", "identity_id", "factor_id", "session_id"),
    "identity.mfa.challenge.expired": _rule("scheduled-mfa", "simcorp-identity", "mfa.challenge.expired", "challenge_id", "identity_id", "factor_id", "session_id"),
    "endpoint.remote_access.succeeded": _rule("endpoint-ad-simulator", "simcorp-endpoint", "remote_access.connected", "identity_id", "source_ip", "identity_event_id"),
    "endpoint.process.discovery": _rule("endpoint-ad-simulator", "simcorp-endpoint", "process.activity", "category", "command_id"),
    "directory.enumeration.completed": _rule("endpoint-ad-simulator", "simcorp-directory", "directory.query.completed", "object_count", "query_category"),
    "directory.account.created": _rule("endpoint-ad-simulator", "simcorp-directory", "account.created", "enabled"),
    "directory.group.membership.changed": _rule("endpoint-ad-simulator", "simcorp-directory", "group.membership.changed", "member"),
    "cloud.authentication.succeeded": _rule("mock-cloud-simulator", "simcorp-storage", "authentication.attempt", "bucket_id", "principal_id", "key_id", "host", "source_ip"),
    "cloud.bucket.enumerated": _rule("mock-cloud-simulator", "simcorp-storage", "bucket.listed", "bucket_id", "principal_id", "key_id", "host", "source_ip"),
    "cloud.policy.changed": _rule("mock-cloud-simulator", "simcorp-storage", "bucket.policy.updated", "bucket_id", "principal_id", "key_id", "host", "source_ip", "policy_hash"),
    "cloud.object.accessed": _rule("mock-cloud-simulator", "simcorp-storage", "object.read", "bucket_id", "principal_id", "key_id", "host", "source_ip", "bytes", "confirmed_count"),
    "cloud.bulk_access.completed": _rule("mock-cloud-simulator", "simcorp-storage", "bulk_read.completed", "bucket_id", "principal_id", "key_id", "host", "source_ip", "confirmed_count"),
    "cloud.bulk_access.blocked": _rule("mock-cloud-simulator", "simcorp-storage", "bulk_read.denied", "bucket_id", "principal_id", "key_id", "host", "source_ip", "confirmed_count"),
    "impact.task.armed": _rule("marker-impact-simulator", "simcorp-file-service", "scheduled_task.enabled", "host", "task_id", "active"),
    "impact.markers.applied": _rule("marker-impact-simulator", "simcorp-file-service", "file.availability.changed", "host", "fixture_id", "available_originals", "marker_count"),
    "recovery.fixture.restored": _rule("marker-impact-simulator", "simcorp-file-service", "backup.restore.completed", "host", "fixture_id", "available_originals"),
}
BOOLEAN_FIELDS = frozenset({"callback_verified", "enabled", "active"})
NUMBER_FIELDS = frozenset({"object_count", "bytes", "confirmed_count", "available_originals", "marker_count"})


def _fact(key, value):
    if key in BOOLEAN_FIELDS:
        return isinstance(value, bool)
    if key in NUMBER_FIELDS:
        return type(value) is int and 0 <= value <= 10**12
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


@lru_cache(maxsize=1)
def _validator():
    return Draft202012Validator(
        json.loads((Path(__file__).resolve().parents[1] / "schemas/learner-audit.v1.json").read_text()),
        format_checker=FormatChecker(),
    )


def validate_audit(event):
    """Validate the emitted learner contract, not canonical or search-result data."""
    try:
        _validator().validate(event)
    except ValidationError:
        raise ValueError("learner audit contract failed") from None
    choices = [fields for _producer, service, operation, fields in RULES.values()
               if service == event["service"] and operation == event["event_type"]]
    if (not choices or not any(set(event["facts"]) <= fields for fields in choices)
            or any(not _fact(key, value) for key, value in event["facts"].items())
            or any((name + "_id" in event) != (name + "_type" in event)
                   for name in ("actor", "target"))):
        raise ValueError("unreviewed learner audit shape")


def project(event):
    """Return only reviewed observable facts, or None for all other records.

    Input is trusted synthetic module telemetry, not arbitrary secret-bearing
    text. Output never includes message/reason, arbitrary nested data or labels.
    Validation and key redaction are not free-text secret detection.
    """
    if not isinstance(event, dict):
        raise ValueError("source event must be an object")
    EventValidator().validate(event)
    if redact_sensitive(event) != event:
        raise ValueError("unredacted source event")
    rule = RULES.get(event["event_type"])
    if rule is None or event["visibility"] != "participant":
        return None
    producer, service, operation, fields = rule
    if event["source"]["kind"] != "module" or event["source"]["component"] != producer:
        return None
    result = {"schema_version": VERSION, "schema_id": "netstrike.learner-audit.v1",
              "event_id": event["event_id"], "exercise_id": event["exercise_id"],
              "run_id": event["run_id"], "timestamp": event["timestamp"],
              "service": service, "event_type": operation,
              "outcome": event["outcome"]["status"], "simulated_service": True,
              "facts": {}}
    for name in ("actor", "target"):
        item = event.get(name)
        if item and item["type"] in ENTITY_TYPES and IDENTIFIER.fullmatch(item["id"]):
            result[name + "_id"] = item["id"]
            result[name + "_type"] = item["type"]
    for key in fields:
        if key in event["data"]:
            value = event["data"][key]
            if not _fact(key, value):
                raise ValueError("invalid approved audit fact")
            result["facts"][key] = deepcopy(value)
    validate_audit(result)
    return result
