"""Contained, vendor-neutral SSO participant experience for the exercise."""

from __future__ import annotations

import hmac
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_USERNAME = re.compile(r"^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.test$")
_CONFIG_FIELDS = frozenset(
    {
        "service_name",
        "heading",
        "introduction",
        "identity",
        "initial_failures_before_mfa",
        "lockout_threshold",
        "mfa_timeout_seconds",
        "messages",
        "suspicious_sessions",
    }
)
_MESSAGE_FIELDS = frozenset(
    {"failure", "locked", "mfa", "success", "suspicious", "rejected"}
)
_GENERATED_SESSION_ID = "sess-sso-current"


class SsoExperienceError(ValueError):
    """Raised when the contained SSO workflow receives an invalid transition."""


class SsoBoundaryError(PermissionError):
    """Raised when a request falls outside the synthetic identity boundary."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: Mapping[str, Any], field_name: str, maximum: int) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item.strip() or len(item) > maximum:
        raise SsoExperienceError(f"{field_name} must be a non-empty string")
    return item.strip()


@dataclass(frozen=True)
class SuspiciousSession:
    """Participant-safe description of one seeded exercise session."""

    session_id: str
    label: str
    location: str
    last_seen: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SuspiciousSession":
        if set(value) != {"id", "label", "location", "last_seen"}:
            raise SsoExperienceError("suspicious session fields are invalid")
        session_id = _required_text(value, "id", 256)
        if not _IDENTIFIER.fullmatch(session_id):
            raise SsoExperienceError("suspicious session id is invalid")
        return cls(
            session_id=session_id,
            label=_required_text(value, "label", 256),
            location=_required_text(value, "location", 256),
            last_seen=_required_text(value, "last_seen", 256),
        )


@dataclass(frozen=True)
class SsoExperienceConfig:  # pylint: disable=too-many-instance-attributes
    """Reviewed SSO text and deterministic state loaded from the scenario."""

    service_name: str
    heading: str
    introduction: str
    identity_id: str
    username: str
    display_name: str
    initial_failures_before_mfa: int
    lockout_threshold: int
    mfa_timeout_seconds: int
    messages: Mapping[str, str]
    suspicious_sessions: tuple[SuspiciousSession, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SsoExperienceConfig":
        if not isinstance(value, Mapping) or set(value) != _CONFIG_FIELDS:
            raise SsoExperienceError("scenario SSO configuration fields are invalid")
        raw_identity = value.get("identity")
        if not isinstance(raw_identity, Mapping) or set(raw_identity) != {
            "id",
            "username",
            "display_name",
        }:
            raise SsoExperienceError("scenario SSO identity fields are invalid")
        identity_id = _required_text(raw_identity, "id", 256)
        username = _required_text(raw_identity, "username", 256).casefold()
        if not _IDENTIFIER.fullmatch(identity_id):
            raise SsoExperienceError("scenario SSO identity id is invalid")
        if not _USERNAME.fullmatch(username):
            raise SsoExperienceError(
                "scenario SSO username must use the reserved .test domain"
            )

        raw_messages = value.get("messages")
        if not isinstance(raw_messages, Mapping) or set(raw_messages) != _MESSAGE_FIELDS:
            raise SsoExperienceError("scenario SSO messages are incomplete")
        messages = {
            field_name: _required_text(raw_messages, field_name, 512)
            for field_name in sorted(_MESSAGE_FIELDS)
        }

        raw_sessions = value.get("suspicious_sessions")
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raise SsoExperienceError(
                "scenario SSO requires at least one suspicious session"
            )
        if not all(isinstance(item, Mapping) for item in raw_sessions):
            raise SsoExperienceError("every suspicious session must be an object")
        sessions = tuple(SuspiciousSession.from_mapping(item) for item in raw_sessions)
        if len({item.session_id for item in sessions}) != len(sessions):
            raise SsoExperienceError("suspicious session ids must be unique")

        initial_failures = value.get("initial_failures_before_mfa")
        lockout_threshold = value.get("lockout_threshold")
        timeout = value.get("mfa_timeout_seconds")
        if not isinstance(initial_failures, int) or initial_failures < 0:
            raise SsoExperienceError(
                "initial_failures_before_mfa must be a non-negative integer"
            )
        if not isinstance(lockout_threshold, int) or lockout_threshold < 1:
            raise SsoExperienceError("lockout_threshold must be a positive integer")
        if not isinstance(timeout, int) or not 10 <= timeout <= 300:
            raise SsoExperienceError(
                "mfa_timeout_seconds must be between 10 and 300"
            )

        return cls(
            service_name=_required_text(value, "service_name", 128),
            heading=_required_text(value, "heading", 256),
            introduction=_required_text(value, "introduction", 512),
            identity_id=identity_id,
            username=username,
            display_name=_required_text(raw_identity, "display_name", 256),
            initial_failures_before_mfa=initial_failures,
            lockout_threshold=lockout_threshold,
            mfa_timeout_seconds=timeout,
            messages=messages,
            suspicious_sessions=sessions,
        )


@dataclass
class _SsoState:  # pylint: disable=too-many-instance-attributes
    view: str = "sign_in"
    failed_attempts: int = 0
    locked: bool = False
    challenge_id: str | None = None
    challenge_expires_at: datetime | None = None
    signed_in: bool = False
    sessions_reviewed: bool = False
    message: str = ""
    username: str | None = None
    history: list[str] = field(default_factory=list)


class SsoExperience:  # pylint: disable=too-many-instance-attributes
    """Stateful SSO simulation with no connection to a real identity provider."""

    def __init__(
        self,
        config: SsoExperienceConfig,
        *,
        identity_state: Callable[[], Any],
        audit_sink: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], Any] = uuid.uuid4,
    ) -> None:
        self.config = config
        self._identity_state = identity_state
        self._audit_sink = audit_sink
        self._clock = clock
        self._id_factory = id_factory
        self._lock = threading.RLock()
        self._state = _SsoState()

    def _event_id(self) -> str:
        return f"sso-{self._id_factory()}"

    def _audit(
        self,
        *,
        action: str,
        result: str,
        credential: str | None = None,
        identity_id: str | None = None,
    ) -> Mapping[str, Any]:
        occurred_at = self._clock().astimezone(timezone.utc)
        payload: dict[str, Any] = {
            "phase": "identity",
            "synthetic_identity": identity_id or self.config.identity_id,
            "occurred_at": occurred_at.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "action": action,
            "result": result,
            "source_event_id": self._event_id(),
        }
        if credential is not None:
            payload.update(
                {
                    "credential_kind": "password",
                    "synthetic_credential": credential,
                }
            )
        return self._audit_sink(payload)

    def _active_suspicious_sessions(self) -> list[dict[str, str]]:
        state = self._identity_state()
        return [
            {
                "id": item.session_id,
                "label": item.label,
                "location": item.location,
                "last_seen": item.last_seen,
            }
            for item in self.config.suspicious_sessions
            if state.sessions.get(item.session_id, {}).get("active") is True
        ]

    def state(self) -> dict[str, Any]:
        """Return participant-safe text and the current workflow view."""

        with self._lock:
            challenge = None
            if self._state.challenge_id and self._state.challenge_expires_at:
                seconds = max(
                    0,
                    int((self._state.challenge_expires_at - self._clock()).total_seconds()),
                )
                challenge = {
                    "id": self._state.challenge_id,
                    "expires_in_seconds": seconds,
                }
            result: dict[str, Any] = {
                "service_name": self.config.service_name,
                "heading": self.config.heading,
                "introduction": self.config.introduction,
                "view": self._state.view,
                "message": self._state.message,
                "failed_attempts": self._state.failed_attempts,
                "challenge": challenge,
                "display_name": (
                    self.config.display_name if self._state.username else None
                ),
                "sessions_reviewed": self._state.sessions_reviewed,
                "has_suspicious_sessions": (
                    self._state.signed_in
                    and bool(self._active_suspicious_sessions())
                ),
            }
            if self._state.sessions_reviewed:
                result["sessions"] = self._active_suspicious_sessions()
            return result

    def sign_in(self, username: Any, credential: Any) -> dict[str, Any]:
        """Advance a deterministic synthetic sign-in without real authentication."""

        if not isinstance(username, str) or not username.strip() or len(username) > 256:
            raise SsoBoundaryError(self.config.messages["rejected"])
        if not isinstance(credential, str) or not credential or len(credential) > 1024:
            raise SsoExperienceError("an exercise access phrase is required")
        normalized_username = username.strip().casefold()

        with self._lock:
            if not hmac.compare_digest(normalized_username, self.config.username):
                self._audit(
                    action="identity.sign_in.rejected",
                    result="denied",
                    identity_id="external-account",
                )
                raise SsoBoundaryError(self.config.messages["rejected"])

            identity = self._identity_state().identities.get(self.config.identity_id)
            if identity is None or identity.get("synthetic") is not True:
                raise SsoBoundaryError(self.config.messages["rejected"])
            self._state.username = self.config.username
            if identity.get("enabled") is not True or self._state.locked:
                self._state.view = "locked"
                self._state.locked = True
                self._state.message = self.config.messages["locked"]
                self._state.history.append("locked")
                self._audit(action="identity.sign_in.attempt", result="blocked")
                return self.state()

            if self._state.signed_in:
                self._state.view = "success"
                self._state.message = self.config.messages["success"]
                return self.state()
            if self._state.challenge_id:
                self._state.view = "mfa"
                self._state.message = self.config.messages["mfa"]
                return self.state()

            if (
                self._state.failed_attempts
                < self.config.initial_failures_before_mfa
            ):
                self._state.failed_attempts += 1
                self._state.locked = (
                    self._state.failed_attempts >= self.config.lockout_threshold
                )
                self._state.view = "locked" if self._state.locked else "failure"
                self._state.message = self.config.messages[
                    "locked" if self._state.locked else "failure"
                ]
                if self._state.locked:
                    identity["enabled"] = False
                self._state.history.append(self._state.view)
                self._audit(
                    action="identity.sign_in.attempt",
                    result="blocked" if self._state.locked else "failure",
                    credential=credential,
                )
                return self.state()

            self._state.challenge_id = str(self._id_factory())
            self._state.challenge_expires_at = self._clock() + timedelta(
                seconds=self.config.mfa_timeout_seconds
            )
            self._state.view = "mfa"
            self._state.message = self.config.messages["mfa"]
            self._state.history.append("mfa")
            self._audit(
                action="identity.sign_in.attempt",
                result="success",
                credential=credential,
            )
            self._audit(action="identity.mfa.challenge.delivered", result="pending")
            return self.state()

    def decide_mfa(self, challenge_id: Any, decision: Any) -> dict[str, Any]:
        """Approve or deny only the currently pending synthetic challenge."""

        if not isinstance(challenge_id, str) or not challenge_id:
            raise SsoExperienceError("challenge id is required")
        if decision not in {"approve", "deny"}:
            raise SsoExperienceError("decision must be approve or deny")
        with self._lock:
            if not self._state.challenge_id or not hmac.compare_digest(
                challenge_id, self._state.challenge_id
            ):
                raise SsoExperienceError("challenge is unknown or no longer active")
            expired = (
                self._state.challenge_expires_at is None
                or self._clock() >= self._state.challenge_expires_at
            )
            identity_state = self._identity_state()
            mfa_state = identity_state.mfa[self.config.identity_id]
            mfa_state["push_count"] += 1
            self._state.challenge_id = None
            self._state.challenge_expires_at = None

            if expired:
                mfa_state["decision"] = "denied"
                self._state.view = "failure"
                self._state.message = self.config.messages["failure"]
                self._state.history.append("mfa_expired")
                self._audit(action="identity.mfa.challenge.expired", result="denied")
                return self.state()

            approved = decision == "approve"
            mfa_state["decision"] = "approved" if approved else "denied"
            self._state.signed_in = approved
            self._state.view = "success" if approved else "failure"
            self._state.message = self.config.messages[
                "success" if approved else "failure"
            ]
            self._state.history.append(f"mfa_{decision}")
            self._audit(
                action=f"identity.mfa.challenge.{decision}",
                result="success" if approved else "denied",
            )
            if approved:
                identity_state.sessions[_GENERATED_SESSION_ID] = {
                    "identity_id": self.config.identity_id,
                    "active": True,
                    "kind": "participant_sso",
                }
                self._audit(action="identity.session.created", result="success")
            return self.state()

    def review_sessions(self) -> dict[str, Any]:
        """Expose only configured exercise sessions after successful MFA."""

        with self._lock:
            if not self._state.signed_in:
                raise SsoExperienceError(
                    "session review requires an approved synthetic sign-in"
                )
            self._state.sessions_reviewed = True
            self._state.view = "suspicious_session"
            self._state.message = self.config.messages["suspicious"]
            self._state.history.append("sessions_reviewed")
            self._audit(action="identity.session.reviewed", result="success")
            return self.state()

    def reset(self) -> None:
        """Remove SSO-created session state and restore the initial view."""

        with self._lock:
            identity_state = self._identity_state()
            identity_state.sessions.pop(_GENERATED_SESSION_ID, None)
            identity_state.identities[self.config.identity_id]["enabled"] = True
            if self.config.identity_id in identity_state.mfa:
                identity_state.mfa[self.config.identity_id].update(
                    {"push_count": 0, "decision": "pending"}
                )
            self._state = _SsoState()

    def baseline_mismatches(self) -> tuple[str, ...]:
        """Return SSO state sections that did not reset to baseline."""

        with self._lock:
            mismatches = []
            if self._state != _SsoState():
                mismatches.append("workflow")
            if _GENERATED_SESSION_ID in self._identity_state().sessions:
                mismatches.append("generated_session")
            return tuple(mismatches)
