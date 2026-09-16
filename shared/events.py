"""Versioned NetStrike exercise-event construction and validation."""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from jsonschema import Draft202012Validator, FormatChecker

CURRENT_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_MAJOR = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "event.v1.json"

_VERSION_PATTERN = re.compile(r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)$")
_SENSITIVE_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "credential",
    "mfasecret",
    "password",
    "refreshtoken",
    "secret",
    "sessiontoken",
    "token",
}


class EventContractError(ValueError):
    """Base error for event-contract failures."""


class EventCompatibilityError(EventContractError):
    """Raised when an event uses an unsupported schema major version."""


class EventValidationError(EventContractError):
    """Raised when an event does not satisfy the JSON Schema."""


class EventLedgerError(EventContractError):
    """Raised when a JSONL ledger violates runtime invariants."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventContractError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    utc_value = _require_aware(value)
    return utc_value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EventLedgerError(f"invalid event timestamp: {value!r}") from exc
    return _require_aware(parsed)


@lru_cache(maxsize=8)
def _load_schema_cached(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    return schema


def load_schema(path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Load a schema without exposing the cached object to mutation."""

    return deepcopy(_load_schema_cached(str(Path(path).resolve())))


def _schema_major(version: Any) -> int:
    if not isinstance(version, str):
        raise EventCompatibilityError("schema_version must be a semantic-version string")
    match = _VERSION_PATTERN.fullmatch(version)
    if not match:
        raise EventCompatibilityError(
            f"schema_version {version!r} is not formatted as MAJOR.MINOR.PATCH"
        )
    return int(match.group("major"))


class EventValidator:  # pylint: disable=too-few-public-methods
    """Validate structural and major-version compatibility requirements."""

    def __init__(self, schema_path: Path | str = DEFAULT_SCHEMA_PATH) -> None:
        self.schema_path = Path(schema_path).resolve()
        self.schema = load_schema(self.schema_path)
        self._validator = Draft202012Validator(
            self.schema,
            format_checker=FormatChecker(),
        )

    def validate(self, event: Mapping[str, Any]) -> None:
        """Raise a contract error when an event is incompatible or malformed."""

        major = _schema_major(event.get("schema_version"))
        if major != SUPPORTED_SCHEMA_MAJOR:
            raise EventCompatibilityError(
                f"unsupported event schema major {major}; "
                f"this consumer supports major {SUPPORTED_SCHEMA_MAJOR}"
            )

        errors = sorted(
            self._validator.iter_errors(dict(event)),
            key=lambda error: [str(part) for part in error.absolute_path],
        )
        if not errors:
            return

        details = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            details.append(f"{location}: {error.message}")
        raise EventValidationError("event schema validation failed: " + "; ".join(details))


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def redact_sensitive(value: Any, sensitive_keys: Iterable[str] | None = None) -> Any:
    """Return a JSON-compatible copy with known secret fields redacted recursively."""

    configured = {_normalized_key(key) for key in (sensitive_keys or _SENSITIVE_KEYS)}

    def redact(item: Any) -> Any:
        if isinstance(item, Mapping):
            output: dict[str, Any] = {}
            for key, child in item.items():
                key_string = str(key)
                if _normalized_key(key_string) in configured:
                    output[key_string] = "[REDACTED]"
                else:
                    output[key_string] = redact(child)
            return output
        if isinstance(item, (list, tuple)):
            return [redact(child) for child in item]
        return deepcopy(item)

    return redact(value)


def entity(
    entity_type: str,
    entity_id: str,
    *,
    display_name: str | None = None,
    role: str | None = None,
) -> dict[str, str]:
    """Build a schema-compatible actor or target object."""

    result = {"type": entity_type, "id": entity_id}
    if display_name:
        result["display_name"] = display_name
    if role:
        result["role"] = role
    return result


def safety_marker(
    *,
    dry_run: bool,
    within_allowlist: bool,
    controls: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the mandatory non-destructive exercise safety marker."""

    return {
        "simulation_only": True,
        "dry_run": dry_run,
        "within_allowlist": within_allowlist,
        "destructive": False,
        "controls": sorted(set(controls)),
    }


@dataclass(frozen=True)
class EventContext:
    """Stable correlation and producer data shared by a run's events."""

    exercise_id: str
    run_id: str
    source_kind: str
    source_component: str
    producer_version: str
    source_host: str | None = None


class EventBuilder:
    """Create validated events while assigning a monotonic local sequence."""

    def __init__(
        self,
        context: EventContext,
        *,
        start_sequence: int = 0,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], Any] = uuid.uuid4,
        validator: EventValidator | None = None,
    ) -> None:
        if start_sequence < 0:
            raise EventContractError("start_sequence cannot be negative")
        self.context = context
        self._sequence = start_sequence
        self._clock = clock
        self._event_id_factory = event_id_factory
        self._validator = validator or EventValidator()

    @property
    def sequence(self) -> int:
        """Return the last successfully validated sequence number."""

        return self._sequence

    # The event contract is deliberately explicit at call sites. Keeping these
    # fields as named-only arguments makes producer mappings reviewable and
    # prevents an untyped catch-all dictionary from bypassing the contract.
    # pylint: disable=too-many-arguments,too-many-locals
    def build(
        self,
        *,
        event_type: str,
        phase: str,
        actor: Mapping[str, Any],
        action: str,
        target: Mapping[str, Any] | None,
        outcome_status: str,
        message: str,
        severity: str = "info",
        visibility: str = "participant",
        outcome_reason: str | None = None,
        dry_run: bool = False,
        within_allowlist: bool = True,
        safety_controls: Iterable[str] = (),
        data: Mapping[str, Any] | None = None,
        attack_technique_id: str | None = None,
        attack_tactic: str | None = None,
        objective_ids: Iterable[str] = (),
        checkpoint_id: str | None = None,
        correlation_ids: Iterable[str] = (),
        raw_data_ref: str | None = None,
        extensions: Mapping[str, Any] | None = None,
        source_event_id: str | None = None,
        integrity_sha256: str | None = None,
        timestamp: datetime | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Build, redact, validate, and sequence one contract-compliant event."""

        if (attack_technique_id is None) != (attack_tactic is None):
            raise EventContractError(
                "attack_technique_id and attack_tactic must be supplied together"
            )

        next_sequence = self._sequence + 1
        source: dict[str, Any] = {
            "kind": self.context.source_kind,
            "component": self.context.source_component,
        }
        if self.context.source_host:
            source["host"] = self.context.source_host

        outcome: dict[str, str] = {"status": outcome_status}
        if outcome_reason:
            outcome["reason"] = outcome_reason

        provenance: dict[str, Any] = {
            "producer": self.context.source_component,
            "producer_version": self.context.producer_version,
        }
        if source_event_id:
            provenance["source_event_id"] = source_event_id
        if integrity_sha256:
            provenance["integrity"] = {
                "algorithm": "sha256",
                "digest": integrity_sha256,
            }

        event: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "event_id": event_id or str(self._event_id_factory()),
            "timestamp": _format_timestamp(timestamp or self._clock()),
            "exercise_id": self.context.exercise_id,
            "run_id": self.context.run_id,
            "sequence": next_sequence,
            "event_type": event_type,
            "phase": phase,
            "source": source,
            "actor": dict(actor),
            "action": action,
            "target": dict(target) if target is not None else None,
            "outcome": outcome,
            "severity": severity,
            "visibility": visibility,
            "safety": safety_marker(
                dry_run=dry_run,
                within_allowlist=within_allowlist,
                controls=safety_controls,
            ),
            "provenance": provenance,
            "message": message,
            "objective_ids": sorted(set(objective_ids)),
            "checkpoint_id": checkpoint_id,
            "correlation_ids": list(dict.fromkeys(correlation_ids)),
            "raw_data_ref": raw_data_ref,
            "data": redact_sensitive(dict(data or {})),
            "extensions": redact_sensitive(dict(extensions or {})),
        }
        if attack_technique_id and attack_tactic:
            event["attack"] = {
                "technique_id": attack_technique_id,
                "tactic": attack_tactic,
            }

        self._validator.validate(event)
        self._sequence = next_sequence
        return event


def correlation_key(event: Mapping[str, Any]) -> tuple[str, str]:
    """Return the exercise/run tuple used for ordering and query correlation."""

    return str(event["exercise_id"]), str(event["run_id"])


class EventLedger:
    """Append validated, redacted events to a JSONL ledger safely."""

    def __init__(
        self,
        path: Path | str,
        *,
        validator: EventValidator | None = None,
        clock: Callable[[], datetime] = _utc_now,
        max_future_skew: timedelta = timedelta(minutes=5),
        load_existing: bool = True,
    ) -> None:
        if max_future_skew < timedelta(0):
            raise EventLedgerError("max_future_skew cannot be negative")
        self.path = Path(path)
        self.validator = validator or EventValidator()
        self._clock = clock
        self._max_future_skew = max_future_skew
        self._event_ids: set[str] = set()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._event_count = 0
        if load_existing and self.path.exists():
            self._load_existing()

    @property
    def event_count(self) -> int:
        """Return the number of validated events known to this ledger."""

        return self._event_count

    def _load_existing(self) -> None:
        for line_number, event in enumerate(iter_jsonl(self.path), start=1):
            try:
                self._check(event, enforce_clock=False)
                self._remember(event)
            except EventContractError as exc:
                raise EventLedgerError(
                    f"invalid existing event at {self.path}:{line_number}: {exc}"
                ) from exc

    def _check(self, event: Mapping[str, Any], *, enforce_clock: bool) -> None:
        self.validator.validate(event)
        event_id = str(event["event_id"])
        if event_id in self._event_ids:
            raise EventLedgerError(f"duplicate event_id: {event_id}")

        key = correlation_key(event)
        sequence = int(event["sequence"])
        previous = self._last_sequence.get(key)
        if previous is not None and sequence <= previous:
            raise EventLedgerError(
                f"out-of-order sequence for {key[0]}/{key[1]}: "
                f"received {sequence} after {previous}"
            )

        if enforce_clock:
            event_time = _parse_timestamp(str(event["timestamp"]))
            now = _require_aware(self._clock())
            if event_time - now > self._max_future_skew:
                raise EventLedgerError(
                    f"event timestamp is more than {self._max_future_skew} in the future"
                )

    def _remember(self, event: Mapping[str, Any]) -> None:
        self._event_ids.add(str(event["event_id"]))
        self._last_sequence[correlation_key(event)] = int(event["sequence"])
        self._event_count += 1

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Redact, validate, persist, and return the stored event."""

        sanitized = redact_sensitive(dict(event))
        self._check(sanitized, enforce_clock=True)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as ledger_file:
            json.dump(sanitized, ledger_file, sort_keys=True, separators=(",", ":"))
            ledger_file.write("\n")
            ledger_file.flush()

        self._remember(sanitized)
        return sanitized


def iter_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL file with line-aware errors."""

    ledger_path = Path(path)
    with ledger_path.open(encoding="utf-8") as ledger_file:
        for line_number, line in enumerate(ledger_file, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventLedgerError(
                    f"invalid JSON at {ledger_path}:{line_number}: {exc.msg}"
                ) from exc
            if not isinstance(event, dict):
                raise EventLedgerError(
                    f"event at {ledger_path}:{line_number} must be a JSON object"
                )
            yield event
