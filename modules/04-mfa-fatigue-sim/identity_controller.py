"""Authenticated HTTP-facing controller for synthetic identity actions."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from identity_actions import SyntheticIdentityState, register_identity_actions
from shared.actions import ActionRegistry, SafeActionAdapter, make_action_request
from shared.events import EventContext, entity


class AuthenticationError(PermissionError):
    """Raised when an API bearer credential is missing or invalid."""


@dataclass(frozen=True)
class Principal:
    """Server-owned identity resolved from one bearer credential."""

    actor_id: str
    role: str


def load_token_principals(raw: str | None = None) -> dict[str, Principal]:
    """Load token-to-principal mappings from JSON without logging token values."""

    value = raw if raw is not None else os.getenv("NETSTRIKE_ACTION_TOKENS", "{}")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("NETSTRIKE_ACTION_TOKENS must be a JSON object")
    principals = {}
    for token, record in parsed.items():
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError("each action token must contain at least 16 characters")
        if not isinstance(record, dict) or set(record) != {"actor_id", "role"}:
            raise ValueError("each action token must map to actor_id and role")
        principals[token] = Principal(str(record["actor_id"]), str(record["role"]))
    return principals


class IdentityController:
    """Own identity state, authentication, action policy, and audit submission."""

    # Runtime collaborators are explicit so tests and the scenario engine can
    # supply authoritative state, time, authentication, and audit persistence.
    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        exercise_id: str,
        run_id: str,
        tokens: Mapping[str, Principal],
        event_sink: Callable[[Mapping[str, Any]], Any],
        run_state: Callable[[str, str], str] = lambda _exercise, _run: "running",
        approval_threshold: int = 4,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.exercise_id = exercise_id
        self.run_id = run_id
        self.tokens = dict(tokens)
        self.state = SyntheticIdentityState.baseline()
        registry = ActionRegistry()
        register_identity_actions(
            registry, self.state, approval_threshold=approval_threshold
        )
        self.adapter = SafeActionAdapter(
            context=EventContext(
                exercise_id=exercise_id,
                run_id=run_id,
                source_kind="action_adapter",
                source_component="identity-action-controller",
                producer_version="1.0.0",
            ),
            registry=registry,
            run_state=run_state,
            event_sink=event_sink,
            clock=clock,
        )

    def authenticate(self, authorization: str | None) -> Principal:
        """Resolve a Bearer token using constant-time comparisons."""

        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("Bearer authentication is required")
        supplied = authorization.removeprefix("Bearer ")
        for token, principal in self.tokens.items():
            if hmac.compare_digest(supplied, token):
                return principal
        raise AuthenticationError("invalid Bearer credential")

    def submit(
        self, principal: Principal, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Build a server-correlated request and submit it to the safe adapter."""

        allowed_fields = {
            "action_id",
            "target",
            "idempotency_key",
            "parameters",
            "dry_run",
            "timeout_seconds",
        }
        if set(payload) - allowed_fields:
            raise ValueError("request contains unsupported fields")
        action_request = make_action_request(
            exercise_id=self.exercise_id,
            run_id=self.run_id,
            actor=entity("service_account", principal.actor_id, role=principal.role),
            action_id=str(payload.get("action_id", "")),
            target=dict(payload.get("target") or {}),
            idempotency_key=str(payload.get("idempotency_key", "")),
            parameters=dict(payload.get("parameters") or {}),
            dry_run=payload.get("dry_run", True),
            timeout_seconds=payload.get("timeout_seconds", 15),
        )
        return self.adapter.execute(action_request)
