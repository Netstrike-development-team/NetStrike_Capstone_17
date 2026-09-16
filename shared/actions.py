"""Fail-closed execution contract for NetStrike state-changing actions."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .events import EventBuilder, EventContext, entity, redact_sensitive

ACTION_SCHEMA_VERSION = "1.0.0"
ACTION_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "action.v1.json"


class ActionContractError(ValueError):
    """Base error for action-contract failures."""


class ActionValidationError(ActionContractError):
    """Raised when an action record is structurally invalid."""


class ActionCancelled(ActionContractError):
    """Raised by a cooperative handler after a fail-safe stop."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ActionContractError("action timestamps must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class ActionValidator:  # pylint: disable=too-few-public-methods
    """Validate request and result records against action contract v1."""

    def __init__(self, schema_path: Path | str = ACTION_SCHEMA_PATH) -> None:
        with Path(schema_path).open(encoding="utf-8") as schema_file:
            self.schema = json.load(schema_file)
        Draft202012Validator.check_schema(self.schema)
        self._validator = Draft202012Validator(
            self.schema, format_checker=FormatChecker()
        )

    def validate(self, record: Mapping[str, Any]) -> None:
        """Raise a concise validation error for a malformed record."""

        version = record.get("schema_version")
        if not isinstance(version, str) or not version.startswith("1."):
            raise ActionValidationError("unsupported action schema major version")
        errors = sorted(
            self._validator.iter_errors(dict(record)),
            key=lambda error: [str(part) for part in error.absolute_path],
        )
        if errors:
            details = []
            for error in errors:
                location = (
                    ".".join(str(part) for part in error.absolute_path) or "<root>"
                )
                details.append(f"{location}: {error.message}")
            raise ActionValidationError("; ".join(details))


@dataclass
class ExecutionControl:
    """Cooperative cancellation and deadline information passed to handlers."""

    deadline: float
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def checkpoint(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        """Fail when cancellation was requested or the deadline has elapsed."""

        if self.cancel_event.is_set():
            raise ActionCancelled("action cancelled by fail-safe stop")
        if monotonic() > self.deadline:
            raise TimeoutError("action deadline exceeded")


@dataclass(frozen=True)
class ActionEffect:
    """Safe handler output retained for evidence and possible rollback."""

    effects: tuple[str, ...] = ()
    rollback_token: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


ActionHandler = Callable[
    [Mapping[str, Any], Mapping[str, Any], ExecutionControl], ActionEffect
]
RollbackHandler = Callable[[str, ExecutionControl], tuple[str, ...]]
ParameterValidator = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class ActionDefinition:  # pylint: disable=too-many-instance-attributes
    """Registered policy and implementation for one state-changing operation."""

    action_id: str
    phase: str
    allowed_roles: frozenset[str]
    allowed_targets: frozenset[str]
    allowed_run_states: frozenset[str]
    max_timeout_seconds: int
    expected_effects: tuple[str, ...]
    rollback_method: str
    handler: ActionHandler
    rollback_handler: RollbackHandler
    parameter_validator: ParameterValidator | None = None

    def __post_init__(self) -> None:
        if not self.allowed_roles or not self.allowed_targets:
            raise ActionContractError("actions require explicit roles and targets")
        if not self.expected_effects or not self.rollback_method:
            raise ActionContractError(
                "actions require expected effects and rollback metadata"
            )
        if self.max_timeout_seconds < 1:
            raise ActionContractError("action timeout must be positive")


class ActionRegistry:
    """Registry that refuses duplicate action identifiers."""

    def __init__(self) -> None:
        self._definitions: dict[str, ActionDefinition] = {}

    def register(self, definition: ActionDefinition) -> None:
        """Register an action exactly once."""

        if definition.action_id in self._definitions:
            raise ActionContractError(
                f"duplicate action registration: {definition.action_id}"
            )
        self._definitions[definition.action_id] = definition

    def get(self, action_id: str) -> ActionDefinition | None:
        """Return a registered action, if present."""

        return self._definitions.get(action_id)


class SafeActionAdapter:
    """Authorize, execute, audit, deduplicate, cancel, and roll back actions."""

    # The adapter intentionally owns several collaborators: they are the
    # enforceable boundary rather than optional behavior in individual modules.
    # pylint: disable=too-many-instance-attributes,too-many-arguments
    def __init__(
        self,
        *,
        context: EventContext,
        registry: ActionRegistry,
        run_state: Callable[[str, str], str],
        event_sink: Callable[[Mapping[str, Any]], Any],
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        validator: ActionValidator | None = None,
    ) -> None:
        self.context = context
        self.registry = registry
        self.run_state = run_state
        self.event_sink = event_sink
        self.clock = clock
        self.monotonic = monotonic
        self.validator = validator or ActionValidator()
        self.events = EventBuilder(context, clock=clock)
        self._results: dict[tuple[str, str], dict[str, Any]] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}
        self._executions: dict[
            str, tuple[ActionDefinition, dict[str, Any], ActionEffect]
        ] = {}
        self._running: dict[str, tuple[str, ExecutionControl]] = {}
        self._stopped_runs: set[str] = set()
        self._lock = threading.RLock()

    # Audit construction keeps its policy fields explicit at each call site.
    # pylint: disable=too-many-arguments
    def _emit(
        self,
        request: Mapping[str, Any],
        event_type: str,
        outcome: str,
        message: str,
        *,
        phase: str = "control",
        within_allowlist: bool = True,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        actor = request.get("actor") or entity("system", "action-adapter")
        target = request.get("target")
        event = self.events.build(
            event_type=event_type,
            phase=phase,
            actor=actor,
            action=str(request.get("action_id") or "action.unknown"),
            target=target,
            outcome_status=outcome,
            message=message,
            visibility="facilitator",
            dry_run=bool(request.get("dry_run", True)),
            within_allowlist=within_allowlist,
            safety_controls=("safe-action-adapter", "role-policy", "target-allowlist"),
            correlation_ids=(
                (str(request["request_id"]),) if request.get("request_id") else ()
            ),
            data=data or {},
        )
        self.event_sink(event)

    @staticmethod
    def _fingerprint(request: Mapping[str, Any]) -> str:
        material = {
            key: request.get(key)
            for key in (
                "exercise_id",
                "run_id",
                "actor",
                "action_id",
                "target",
                "parameters",
                "dry_run",
                "timeout_seconds",
            )
        }
        payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    # Result construction mirrors the required schema fields.
    # pylint: disable=too-many-arguments
    def _result(
        self,
        request: Mapping[str, Any],
        *,
        status: str,
        successful: bool,
        started_at: datetime,
        cached: bool = False,
        effects: tuple[str, ...] = (),
        rollback: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        message: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": ACTION_SCHEMA_VERSION,
            "record_type": "result",
            "request_id": request["request_id"],
            "idempotency_key": request["idempotency_key"],
            "exercise_id": request["exercise_id"],
            "run_id": request["run_id"],
            "action_id": request["action_id"],
            "target": deepcopy(request["target"]),
            "status": status,
            "successful": successful,
            "started_at": _timestamp(started_at),
            "finished_at": _timestamp(self.clock()),
            "cached": cached,
            "effects": list(effects),
            "rollback": dict(
                rollback
                or {
                    "supported": False,
                    "required": False,
                    "attempted": False,
                    "succeeded": False,
                }
            ),
            "error_code": error_code,
            "message": message,
        }
        self.validator.validate(result)
        return result

    def _deny(
        self,
        request: Mapping[str, Any],
        started_at: datetime,
        code: str,
        message: str,
        *,
        within_allowlist: bool = True,
    ) -> dict[str, Any]:
        self._emit(
            request,
            "action.authorization.denied",
            "denied",
            message,
            within_allowlist=within_allowlist,
            data={"error_code": code},
        )
        return self._result(
            request,
            status="denied",
            successful=False,
            started_at=started_at,
            error_code=code,
            message=message,
        )

    # Explicit request fields make enforcement reviewable; a generic options
    # object here would make it easy to accidentally bypass a control.
    # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one valid request, returning a validated immutable result copy."""

        request = redact_sensitive(dict(request))
        self.validator.validate(request)
        started_at = self.clock()
        self._emit(request, "action.requested", "pending", "Action requested")

        if (
            request["exercise_id"] != self.context.exercise_id
            or request["run_id"] != self.context.run_id
        ):
            return self._deny(
                request,
                started_at,
                "correlation_mismatch",
                "Request is for another exercise run",
            )

        key = (request["run_id"], request["idempotency_key"])
        fingerprint = self._fingerprint(request)
        with self._lock:
            if key in self._results:
                if self._fingerprints[key] != fingerprint:
                    return self._deny(
                        request,
                        started_at,
                        "idempotency_conflict",
                        "Idempotency key was reused for a different action",
                    )
                cached = deepcopy(self._results[key])
                cached["cached"] = True
                self.validator.validate(cached)
                self._emit(
                    request,
                    "action.result.replayed",
                    "success",
                    "Returned cached action result",
                )
                return cached

        definition = self.registry.get(request["action_id"])
        if definition is None:
            return self._deny(
                request, started_at, "unregistered_action", "Action is not registered"
            )
        if request["run_id"] in self._stopped_runs:
            return self._deny(
                request, started_at, "run_stopped", "Run is under fail-safe stop"
            )
        if (
            self.run_state(request["exercise_id"], request["run_id"])
            not in definition.allowed_run_states
        ):
            return self._deny(
                request,
                started_at,
                "invalid_run_state",
                "Action is not allowed in the current run state",
            )
        if request["actor"]["role"] not in definition.allowed_roles:
            return self._deny(
                request, started_at, "role_denied", "Actor role is not authorized"
            )
        target_key = f"{request['target']['type']}:{request['target']['id']}"
        if target_key not in definition.allowed_targets:
            return self._deny(
                request,
                started_at,
                "target_denied",
                "Target is outside the action allowlist",
                within_allowlist=False,
            )
        if request["timeout_seconds"] > definition.max_timeout_seconds:
            return self._deny(
                request,
                started_at,
                "timeout_exceeds_policy",
                "Requested timeout exceeds action policy",
            )
        if definition.parameter_validator:
            try:
                definition.parameter_validator(request["parameters"])
            except (TypeError, ValueError, ActionContractError) as exc:
                return self._deny(request, started_at, "invalid_parameters", str(exc))

        self._emit(
            request,
            "action.authorization.granted",
            "success",
            "Action authorized",
            phase=definition.phase,
        )
        if request["dry_run"]:
            result = self._result(
                request,
                status="dry_run",
                successful=True,
                started_at=started_at,
                effects=definition.expected_effects,
                rollback={
                    "supported": True,
                    "required": False,
                    "attempted": False,
                    "succeeded": False,
                    "method": definition.rollback_method,
                },
                message="Dry run passed; handler was not invoked",
            )
            self._store(key, fingerprint, result)
            self._emit(
                request,
                "action.execution.completed",
                "success",
                result["message"],
                phase=definition.phase,
                data={"status": "dry_run", "effects": result["effects"]},
            )
            return deepcopy(result)

        control = ExecutionControl(self.monotonic() + request["timeout_seconds"])
        with self._lock:
            self._running[request["request_id"]] = (request["run_id"], control)
        self._emit(
            request,
            "action.execution.started",
            "pending",
            "Action execution started",
            phase=definition.phase,
        )
        try:
            effect = definition.handler(
                request["parameters"], request["target"], control
            )
            control.checkpoint(self.monotonic)
        except (ActionCancelled, TimeoutError) as exc:
            status = "cancelled" if isinstance(exc, ActionCancelled) else "timed_out"
            result = self._result(
                request,
                status=status,
                successful=False,
                started_at=started_at,
                error_code=status,
                message=str(exc),
            )
        # A handler is an extension boundary. Unknown faults are converted to a
        # redacted failure result rather than crossing into the controller.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result = self._result(
                request,
                status="failed",
                successful=False,
                started_at=started_at,
                error_code="handler_error",
                message=f"Handler failed: {type(exc).__name__}",
            )
        else:
            rollback = {
                "supported": True,
                "required": False,
                "attempted": False,
                "succeeded": False,
                "method": definition.rollback_method,
            }
            if effect.rollback_token:
                rollback["token"] = effect.rollback_token
            result = self._result(
                request,
                status="executed",
                successful=True,
                started_at=started_at,
                effects=effect.effects,
                rollback=rollback,
                message="Action executed successfully",
            )
            with self._lock:
                self._executions[request["request_id"]] = (
                    definition,
                    dict(request),
                    effect,
                )
        finally:
            with self._lock:
                self._running.pop(request["request_id"], None)

        self._store(key, fingerprint, result)
        self._emit(
            request,
            "action.execution.completed",
            "success" if result["successful"] else "failure",
            result["message"],
            phase=definition.phase,
            data={"status": result["status"], "effects": result["effects"]},
        )
        return deepcopy(result)

    def _store(
        self, key: tuple[str, str], fingerprint: str, result: Mapping[str, Any]
    ) -> None:
        with self._lock:
            self._fingerprints[key] = fingerprint
            self._results[key] = deepcopy(dict(result))

    def activate_fail_safe(
        self, run_id: str, operator: Mapping[str, Any], reason: str
    ) -> int:
        """Stop new work and cooperatively cancel running actions for a run."""

        if operator.get("role") not in {"facilitator", "technical_operator"}:
            raise ActionContractError(
                "fail-safe stop requires an exercise-control role"
            )
        if not reason.strip():
            raise ActionContractError("fail-safe stop requires a reason")
        request = {
            "request_id": str(uuid.uuid4()),
            "actor": dict(operator),
            "target": entity("exercise_run", run_id),
            "action_id": "control.fail_safe.activate",
            "dry_run": False,
        }
        with self._lock:
            self._stopped_runs.add(run_id)
            controls = [
                control
                for active_run, control in self._running.values()
                if active_run == run_id
            ]
            for control in controls:
                control.cancel_event.set()
        self._emit(
            request,
            "action.fail_safe.activated",
            "success",
            "Fail-safe stop activated",
            data={"reason": reason, "cancelled_actions": len(controls)},
        )
        return len(controls)

    def rollback(self, request_id: str, operator: Mapping[str, Any]) -> tuple[str, ...]:
        """Run the registered rollback for a successful prior execution."""

        with self._lock:
            execution = self._executions.get(request_id)
        if execution is None:
            raise ActionContractError("no rollback-capable execution found")
        definition, request, effect = execution
        if operator.get("role") not in {"facilitator", "technical_operator"}:
            raise ActionContractError("rollback requires an exercise-control role")
        if not effect.rollback_token:
            raise ActionContractError("execution did not return a rollback token")
        control = ExecutionControl(self.monotonic() + definition.max_timeout_seconds)
        changes = definition.rollback_handler(effect.rollback_token, control)
        control.checkpoint(self.monotonic)
        audit_request = dict(request)
        audit_request["actor"] = dict(operator)
        self._emit(
            audit_request,
            "action.rollback.completed",
            "success",
            "Action rollback completed",
            phase=definition.phase,
            data={"effects": changes, "method": definition.rollback_method},
        )
        return changes


# Request fields intentionally remain explicit and keyword-only.
# pylint: disable=too-many-arguments
def make_action_request(
    *,
    exercise_id: str,
    run_id: str,
    actor: Mapping[str, Any],
    action_id: str,
    target: Mapping[str, Any],
    idempotency_key: str,
    parameters: Mapping[str, Any] | None = None,
    dry_run: bool = True,
    timeout_seconds: int = 30,
    clock: Callable[[], datetime] = _utc_now,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Construct and validate a v1 action request."""

    request = {
        "schema_version": ACTION_SCHEMA_VERSION,
        "record_type": "request",
        "request_id": request_id or str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "timestamp": _timestamp(clock()),
        "exercise_id": exercise_id,
        "run_id": run_id,
        "actor": dict(actor),
        "action_id": action_id,
        "target": dict(target),
        "parameters": redact_sensitive(dict(parameters or {})),
        "dry_run": dry_run,
        "timeout_seconds": timeout_seconds,
    }
    ActionValidator().validate(request)
    return request
