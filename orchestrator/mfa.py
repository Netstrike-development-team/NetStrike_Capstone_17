"""Run-scoped, entirely local MFA challenges driven by reviewed MSEL items."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Mapping

from shared.events import EventBuilder, EventContext, entity

from .controller import AutomationResult, ControllerError
from .scenario import ScenarioItem


class ScheduledMfa:
    """Explicit human decisions; never push notifications or issue real tokens."""

    # Collaborators form the explicit audit, state, and exercise-clock boundary.
    # pylint: disable=too-many-arguments,too-many-instance-attributes,too-many-locals
    def __init__(
        self, *, exercise_id: str, run_id: str, configuration: Mapping[str, Any],
        identity_state: Callable[[], Any], run_state: Callable[[], str],
        elapsed: Callable[[], int], event_sink: Callable[[Mapping[str, Any]], Any],
        sequence_factory: Callable[[], int], clock: Callable[[], datetime],
        state_lock: Any,
    ) -> None:
        required = {"seed", "identity_id", "session_id", "factor_id", "timeout_seconds"}
        if not isinstance(configuration, Mapping) or set(configuration) != required:
            raise ValueError("scheduled MFA configuration fields are invalid")
        for name in required - {"timeout_seconds"}:
            if not isinstance(configuration[name], str) or not configuration[name].strip():
                raise ValueError("scheduled MFA identifiers must be non-empty strings")
        timeout = configuration["timeout_seconds"]
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 300:
            raise ValueError("scheduled MFA timeout must be between 1 and 300 seconds")
        self.config = dict(configuration)
        self.run_id = run_id
        self.identity_state = identity_state
        self.run_state = run_state
        self.elapsed = elapsed
        self.sink = event_sink
        self.history: list[dict[str, Any]] = []
        self.pending: dict[str, Any] | None = None
        self._lock = state_lock
        state = identity_state()
        identity = state.identities.get(self.config["identity_id"], {})
        if not identity.get("synthetic"):
            raise ValueError("scheduled MFA requires a baseline synthetic identity")
        for collection, key in ((state.sessions, "session_id"), (state.factors, "factor_id")):
            owner = collection.get(self.config[key], {}).get("identity_id")
            if owner != self.config["identity_id"]:
                raise ValueError("scheduled MFA references must belong to its identity")
        self.credential_version = identity["credential_version"]
        self.events = EventBuilder(
            EventContext(exercise_id=exercise_id, run_id=run_id,
                         source_kind="module", source_component="scheduled-mfa",
                         producer_version="1.0.0"),
            clock=clock, sequence_factory=sequence_factory,
        )

    def _blocked_reason(self) -> str | None:
        state = self.identity_state()
        identity = state.identities[self.config["identity_id"]]
        if not identity["enabled"]:
            return "account_disabled"
        if not state.sessions[self.config["session_id"]]["active"]:
            return "session_revoked"
        if not state.factors[self.config["factor_id"]]["active"]:
            return "factor_removed"
        if identity["credential_version"] != self.credential_version:
            return "credential_rotated"
        return None

    def _record(self, challenge: dict[str, Any], outcome: str, reason: str,
                actor: Mapping[str, Any] | None = None,
                occurred_at_seconds: int | None = None) -> None:
        status = {"delivered": "pending", "approved": "success",
                  "denied": "denied", "expired": "denied", "blocked": "blocked",
                  "cancelled": "cancelled"}[outcome]
        evidence = self.events.build(
            event_type=f"identity.mfa.challenge.{outcome}", phase="identity",
            actor=actor or entity("system", "scenario-engine", role="scenario_engine"),
            action=f"identity.mfa.challenge.{outcome}",
            target=entity("identity", self.config["identity_id"]),
            outcome_status=status, outcome_reason=reason,
            message=f"Synthetic MFA challenge {outcome.replace('_', ' ')}",
            visibility="participant", objective_ids=("LO1", "LO2"),
            correlation_ids=(challenge["id"], self.config["session_id"]),
            safety_controls=("synthetic-only", "no-network", "explicit-human-decision",
                             "exercise-clock", "containment-gated"),
            data={"challenge_id": challenge["id"], "msel_id": challenge["msel_id"],
                  "identity_id": self.config["identity_id"],
                  "session_id": self.config["session_id"],
                  "factor_id": self.config["factor_id"],
                  "elapsed_seconds": (
                      self.elapsed() if occurred_at_seconds is None else occurred_at_seconds
                  ),
                  "reason": reason,
                  "delivered_at_seconds": challenge["delivered_at_seconds"],
                  "expires_at_seconds": challenge["expires_at_seconds"]},
        )
        self.sink(evidence)
        challenge.update(outcome=outcome, reason=reason, evidence_id=evidence["event_id"])
        self.identity_state().mfa[self.config["identity_id"]]["decision"] = (
            "pending" if outcome == "delivered" else outcome
        )

    def advance(self, _elapsed_seconds: int) -> None:
        """Expire or invalidate pending work without depending on browser activity."""

        with self._lock:
            if self.pending is None:
                return
            reason = self._blocked_reason()
            if reason or self.elapsed() >= self.pending["expires_at_seconds"]:
                self._record(self.pending, "cancelled" if reason else "expired",
                             reason or "exercise_timeout",
                             occurred_at_seconds=(self.elapsed() if reason
                                                  else self.pending["expires_at_seconds"]))
                self.pending = None

    def deliver(self, item: ScenarioItem, run_id: str) -> AutomationResult:
        """MSEL handler: deliver only a reviewed, local, synthetic challenge."""

        with self._lock:
            if run_id != self.run_id or self.run_state() != "running":
                return AutomationResult(False, "MFA delivery requires the current running exercise")
            self.advance(self.elapsed())
            if self.pending is not None:
                return AutomationResult(False, "A synthetic challenge is already pending")
            challenge = {
                "id": "mfa-" + str(uuid.uuid5(uuid.NAMESPACE_URL,
                        f"{self.run_id}:{self.config['seed']}:{item.item_id}")),
                "msel_id": item.item_id,
                "delivered_at_seconds": self.elapsed(),
                "expires_at_seconds": self.elapsed() + self.config["timeout_seconds"],
            }
            self.history.append(challenge)
            reason = self._blocked_reason()
            self._record(challenge, "blocked" if reason else "delivered",
                         reason or "awaiting_human_decision")
            if not reason:
                self.identity_state().mfa[self.config["identity_id"]]["push_count"] += 1
                self.pending = challenge
            return AutomationResult(True, "Synthetic MFA attempt processed",
                                    {"challenge_id": challenge["id"],
                                     "outcome": challenge["outcome"]})

    def decide(self, challenge_id: Any, decision: Any, actor: Mapping[str, Any]) -> None:
        """Resolve one pending challenge with server-owned role attribution."""

        with self._lock:
            if actor.get("role") not in {"facilitator", "simulated_user"}:
                raise ControllerError("MFA decisions require facilitator or simulated_user role")
            if self.run_state() != "running":
                raise ControllerError("MFA decisions require a running exercise")
            if (not isinstance(challenge_id, str) or not isinstance(decision, str)
                    or decision not in {"approve", "deny"}):
                raise ControllerError("MFA decision fields are invalid")
            self.advance(self.elapsed())
            if self.pending is None or self.pending["id"] != challenge_id:
                raise ControllerError("No matching pending challenge in this run")
            self._record(self.pending, "approved" if decision == "approve" else "denied",
                         "human_decision", actor)
            self.pending = None

    def stop(self) -> None:
        """Cancel any pending challenge on emergency stop."""

        with self._lock:
            if self.pending is not None:
                self._record(self.pending, "cancelled", "fail_safe_stop")
                self.pending = None

    def snapshot(self) -> dict[str, Any]:
        """Return copied operational state and evaluator evidence, never secrets."""

        with self._lock:
            pending = deepcopy(self.pending)
            if pending:
                pending["expires_in_seconds"] = max(
                    0, pending["expires_at_seconds"] - self.elapsed()
                )
                pending["kind"] = "scheduled"
            return {"pending": pending, "history": deepcopy(self.history),
                    "state": self.run_state(),
                    "identity_id": self.config["identity_id"]}
