"""Safe capture and normalization of synthetic identity interactions."""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from shared.events import EventBuilder, EventContext, entity

from .store import PortalStore


PHASES = frozenset(
    {
        "setup",
        "reconnaissance",
        "identity",
        "endpoint_ad",
        "cloud",
        "impact_recovery",
        "control",
        "post_exercise",
    }
)
RESULTS = frozenset(
    {
        "success",
        "failure",
        "denied",
        "blocked",
        "pending",
        "cancelled",
        "error",
        "unknown",
    }
)
CREDENTIAL_KINDS = frozenset(
    {"password", "session_cookie", "access_token", "mfa_code"}
)
_INPUT_FIELDS = frozenset(
    {
        "phase",
        "synthetic_identity",
        "occurred_at",
        "action",
        "result",
        "source_event_id",
        "synthetic_credential",
        "credential_kind",
    }
)
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class IdentityAuditError(ValueError):
    """Raised when an identity interaction cannot be safely recorded."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(
    payload: Mapping[str, Any], field: str, *, maximum: int
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise IdentityAuditError(f"{field} must be a non-empty string")
    return value.strip()


def _occurred_at(value: Any, clock: Callable[[], datetime]) -> datetime:
    if value is None:
        result = clock()
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IdentityAuditError("occurred_at must be an RFC 3339 timestamp") from exc
    else:
        raise IdentityAuditError("occurred_at must be an RFC 3339 timestamp")
    if result.tzinfo is None or result.utcoffset() is None:
        raise IdentityAuditError("occurred_at must include a UTC offset")
    return result.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class IdentityAuditRecorder:  # pylint: disable=too-few-public-methods
    """Turn allowlisted service submissions into safe, queryable evidence."""

    def __init__(
        self,
        store: PortalStore,
        *,
        audit_key: bytes,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if len(audit_key) < 32:
            raise ValueError("identity audit key must contain at least 32 bytes")
        self.store = store
        self._audit_key = bytes(audit_key)
        self._clock = clock
        self._lock = threading.Lock()

    def _reference(
        self,
        *,
        run_id: str,
        identity_id: str,
        credential_kind: str,
        credential: str,
    ) -> str:
        material = "\0".join(
            (run_id, identity_id, credential_kind, credential)
        ).encode("utf-8")
        digest = hmac.new(self._audit_key, material, hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    # Correlation fields are explicit so callers cannot override run ownership.
    # pylint: disable=too-many-locals,too-many-branches
    def record(
        self,
        *,
        exercise_id: str,
        run_id: str,
        source_service: str,
        sequence_factory: Callable[[], int],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate, transform, and atomically persist one interaction."""

        if not isinstance(payload, Mapping):
            raise IdentityAuditError("request body must be a JSON object")
        unknown = set(payload) - _INPUT_FIELDS
        if unknown:
            raise IdentityAuditError("request contains unsupported fields")
        if not _COMPONENT.fullmatch(source_service) or len(source_service) > 128:
            raise IdentityAuditError("configured source service is invalid")

        phase = _required_text(payload, "phase", maximum=64)
        if phase not in PHASES:
            raise IdentityAuditError("phase is not supported")
        identity_id = _required_text(payload, "synthetic_identity", maximum=256)
        if not _ENTITY_ID.fullmatch(identity_id):
            raise IdentityAuditError("synthetic_identity contains unsupported characters")
        action = _required_text(payload, "action", maximum=128)
        if not _EVENT_NAME.fullmatch(action):
            raise IdentityAuditError("action must use the event-name format")
        result = _required_text(payload, "result", maximum=32)
        if result not in RESULTS:
            raise IdentityAuditError("result is not supported")
        source_event_id = _required_text(payload, "source_event_id", maximum=256)
        occurred_at = _occurred_at(payload.get("occurred_at"), self._clock)

        credential = payload.get("synthetic_credential")
        credential_kind = payload.get("credential_kind")
        if (credential is None) != (credential_kind is None):
            raise IdentityAuditError(
                "synthetic_credential and credential_kind must be supplied together"
            )
        submission_reference = None
        if credential is not None:
            if not isinstance(credential, str) or not credential or len(credential) > 1024:
                raise IdentityAuditError(
                    "synthetic_credential must be a non-empty bounded string"
                )
            if credential_kind not in CREDENTIAL_KINDS:
                raise IdentityAuditError("credential_kind is not supported")
            submission_reference = self._reference(
                run_id=run_id,
                identity_id=identity_id,
                credential_kind=credential_kind,
                credential=credential,
            )

        comparable = {
            "phase": phase,
            "synthetic_identity": identity_id,
            "occurred_at": _format_timestamp(occurred_at),
            "action": action,
            "result": result,
            "source_service": source_service,
            "source_event_id": source_event_id,
            "credential_kind": credential_kind,
            "submission_reference": submission_reference,
        }
        with self._lock:
            existing = self.store.identity_audit_by_source(
                exercise_id, run_id, source_service, source_event_id
            )
            if existing is not None:
                existing_comparable = {
                    key: existing[key] for key in comparable
                }
                if not hmac.compare_digest(
                    repr(sorted(comparable.items())),
                    repr(sorted(existing_comparable.items())),
                ):
                    raise IdentityAuditError(
                        "source_event_id already identifies a different interaction"
                    )
                return {**existing, "duplicate": True}

            audit_id = str(uuid.uuid4())
            builder = EventBuilder(
                EventContext(
                    exercise_id=exercise_id,
                    run_id=run_id,
                    source_kind="module",
                    source_component=source_service,
                    producer_version="1.0.0",
                ),
                clock=self._clock,
                sequence_factory=sequence_factory,
            )
            event = builder.build(
                event_type="identity.interaction.recorded",
                phase=phase,
                actor=entity("identity", identity_id),
                action=action,
                target=entity("identity_service", source_service),
                outcome_status=result,
                message="Recorded a synthetic identity interaction",
                visibility="facilitator",
                dry_run=False,
                safety_controls=(
                    "synthetic-data",
                    "allowlisted-service",
                    "one-way-credential-reference",
                ),
                objective_ids=("LO1",),
                source_event_id=source_event_id,
                timestamp=occurred_at,
                data={
                    "audit_id": audit_id,
                    "credential_kind": credential_kind,
                    "submission_reference": submission_reference,
                },
            )
            record = {
                "audit_id": audit_id,
                "event_id": event["event_id"],
                "exercise_id": exercise_id,
                "run_id": run_id,
                **comparable,
            }
            self.store.append_identity_audit(event, record)
            return {**record, "provenance": event["provenance"], "duplicate": False}
