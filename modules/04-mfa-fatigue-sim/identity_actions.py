"""Synthetic identity state and safe-action registrations for the MFA scenario."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from shared.actions import (
    ActionContractError,
    ActionDefinition,
    ActionEffect,
    ActionRegistry,
    ExecutionControl,
)

IDENTITY_ROLES = frozenset({"identity_responder", "facilitator"})
RUNNING = frozenset({"running"})


@dataclass
class SyntheticIdentityState:
    """Run-scoped identity state containing no reusable credentials."""

    identities: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    factors: dict[str, dict[str, Any]] = field(default_factory=dict)
    mfa: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollbacks: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)
    _rollback_sequence: int = 0

    @classmethod
    def baseline(cls) -> "SyntheticIdentityState":
        """Return the deterministic checkpoint-one identity fixture."""

        return cls(
            identities={
                "sarah": {
                    "display_name": "Sarah Mitchell",
                    "enabled": True,
                    "credential_version": 1,
                    "synthetic": True,
                }
            },
            sessions={
                "sess-red-01": {"identity_id": "sarah", "active": True},
                "sess-sarah-01": {"identity_id": "sarah", "active": True},
            },
            factors={
                "factor-red-01": {
                    "identity_id": "sarah",
                    "active": True,
                    "kind": "simulated_push",
                }
            },
            mfa={"sarah": {"push_count": 0, "decision": "pending"}},
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a defensive state copy for evidence and readiness checks."""

        return {
            "identities": deepcopy(self.identities),
            "sessions": deepcopy(self.sessions),
            "factors": deepcopy(self.factors),
            "mfa": deepcopy(self.mfa),
        }

    def _save_rollback(self, collection: str, item_id: str) -> str:
        collection_data = getattr(self, collection)
        if item_id not in collection_data:
            raise ActionContractError(
                f"unknown synthetic target: {collection}:{item_id}"
            )
        self._rollback_sequence += 1
        token = f"identity-rb-{self._rollback_sequence}"
        self._rollbacks[token] = (
            collection,
            item_id,
            deepcopy(collection_data[item_id]),
        )
        return token

    def set_value(
        self,
        collection: str,
        item_id: str,
        field_name: str,
        value: Any,
        control: ExecutionControl,
    ) -> str:
        """Change one allowlisted field and return a one-use rollback token."""

        control.checkpoint()
        token = self._save_rollback(collection, item_id)
        getattr(self, collection)[item_id][field_name] = value
        return token

    def reset_credential(self, identity_id: str, control: ExecutionControl) -> str:
        """Rotate a synthetic credential version without storing a secret."""

        control.checkpoint()
        token = self._save_rollback("identities", identity_id)
        identity = self.identities[identity_id]
        identity["credential_version"] += 1
        return token

    def record_push(
        self, identity_id: str, threshold: int, control: ExecutionControl
    ) -> str:
        """Record one synthetic challenge and its deterministic outcome."""

        control.checkpoint()
        token = self._save_rollback("mfa", identity_id)
        state = self.mfa[identity_id]
        state["push_count"] += 1
        state["decision"] = "approved" if state["push_count"] >= threshold else "denied"
        return token

    def record_decision(
        self, identity_id: str, approved: bool, control: ExecutionControl
    ) -> str:
        """Record the simulated user's explicit challenge decision."""

        control.checkpoint()
        token = self._save_rollback("mfa", identity_id)
        self.mfa[identity_id]["decision"] = "approved" if approved else "denied"
        return token

    def rollback(self, token: str, control: ExecutionControl) -> tuple[str, ...]:
        """Restore the exact prior object represented by a one-use token."""

        control.checkpoint()
        try:
            collection, item_id, previous = self._rollbacks.pop(token)
        except KeyError as exc:
            raise ActionContractError("unknown or already-used rollback token") from exc
        getattr(self, collection)[item_id] = previous
        return (f"restored {collection}:{item_id}",)


def _no_parameters(parameters: Mapping[str, Any]) -> None:
    if parameters:
        raise ValueError("this action accepts no parameters")


def _decision_parameters(parameters: Mapping[str, Any]) -> None:
    if set(parameters) != {"approved"} or not isinstance(parameters["approved"], bool):
        raise ValueError("approved must be the only parameter and must be boolean")


def register_identity_actions(
    registry: ActionRegistry,
    state: SyntheticIdentityState,
    *,
    approval_threshold: int = 4,
) -> None:
    """Register checkpoint-one identity containment actions."""

    def revoke_session(_params, target, control):
        token = state.set_value("sessions", target["id"], "active", False, control)
        return ActionEffect((f"revoked session {target['id']}",), token)

    def remove_factor(_params, target, control):
        token = state.set_value("factors", target["id"], "active", False, control)
        return ActionEffect((f"removed factor {target['id']}",), token)

    def disable_account(_params, target, control):
        token = state.set_value("identities", target["id"], "enabled", False, control)
        return ActionEffect((f"disabled identity {target['id']}",), token)

    def reset_credential(_params, target, control):
        token = state.reset_credential(target["id"], control)
        return ActionEffect((f"rotated synthetic credential {target['id']}",), token)

    def record_push(_params, target, control):
        token = state.record_push(target["id"], approval_threshold, control)
        decision = state.mfa[target["id"]]["decision"]
        return ActionEffect((f"recorded MFA challenge outcome {decision}",), token)

    def record_decision(params, target, control):
        token = state.record_decision(target["id"], params["approved"], control)
        decision = state.mfa[target["id"]]["decision"]
        return ActionEffect((f"recorded simulated-user decision {decision}",), token)

    definitions = (
        (
            "identity.session.revoke",
            "session:sess-red-01",
            revoke_session,
            "mark session active",
        ),
        (
            "identity.factor.remove",
            "mfa_factor:factor-red-01",
            remove_factor,
            "restore factor state",
        ),
        (
            "identity.account.disable",
            "identity:sarah",
            disable_account,
            "restore account enabled state",
        ),
        (
            "identity.credential.reset",
            "identity:sarah",
            reset_credential,
            "restore credential version",
        ),
    )
    for action_id, target, handler, rollback_method in definitions:
        registry.register(
            ActionDefinition(
                action_id=action_id,
                phase="identity",
                allowed_roles=IDENTITY_ROLES,
                allowed_targets=frozenset({target}),
                allowed_run_states=RUNNING,
                max_timeout_seconds=15,
                expected_effects=(action_id,),
                rollback_method=rollback_method,
                handler=handler,
                rollback_handler=state.rollback,
                parameter_validator=_no_parameters,
            )
        )

    registry.register(
        ActionDefinition(
            action_id="identity.mfa.challenge.record",
            phase="identity",
            allowed_roles=frozenset({"scenario_engine", "facilitator"}),
            allowed_targets=frozenset({"identity:sarah"}),
            allowed_run_states=RUNNING,
            max_timeout_seconds=15,
            expected_effects=("record synthetic MFA challenge",),
            rollback_method="restore prior MFA challenge state",
            handler=record_push,
            rollback_handler=state.rollback,
            parameter_validator=_no_parameters,
        )
    )
    registry.register(
        ActionDefinition(
            action_id="identity.mfa.decision.record",
            phase="identity",
            allowed_roles=frozenset({"simulated_user", "facilitator"}),
            allowed_targets=frozenset({"identity:sarah"}),
            allowed_run_states=RUNNING,
            max_timeout_seconds=15,
            expected_effects=("record simulated-user MFA decision",),
            rollback_method="restore prior MFA decision",
            handler=record_decision,
            rollback_handler=state.rollback,
            parameter_validator=_decision_parameters,
        )
    )
