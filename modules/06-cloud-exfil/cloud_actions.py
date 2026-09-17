"""Deterministic mock-cloud state and safe-action registrations."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from shared.actions import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionError,
    ActionRegistry,
    ExecutionControl,
    SafeActionAdapter,
)
from shared.events import EventContext

CLOUD_ROLES = frozenset({"cloud_responder", "facilitator"})
CONTROL_ROLES = frozenset({"technical_operator", "facilitator"})
PRINCIPAL_ID = "svc-cloud-backup"
KEY_ID = "svc-cloud-backup-key-01"
BUCKET_ID = "simcorp-customer-exports"
APPROVED_POLICY_ID = "simcorp-export-read-v1"
ALTERED_POLICY_ID = "simcorp-export-expanded-v1"


def _policy_hash(policy_id: str) -> str:
    return hashlib.sha256(policy_id.encode("utf-8")).hexdigest()


@dataclass
class MockCloudState:
    """Run-scoped mock state containing synthetic metadata and no key material."""

    principals: dict[str, dict[str, Any]] = field(default_factory=dict)
    keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    buckets: dict[str, dict[str, Any]] = field(default_factory=dict)
    exposure: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollbacks: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollback_sequence: int = 0

    @classmethod
    def baseline(cls) -> "MockCloudState":
        """Return the approved pre-exercise mock-cloud fixture."""

        approved_hash = _policy_hash(APPROVED_POLICY_ID)
        return cls(
            principals={
                PRINCIPAL_ID: {
                    "enabled": True,
                    "synthetic": True,
                    "kind": "service",
                }
            },
            keys={
                KEY_ID: {
                    "principal_id": PRINCIPAL_ID,
                    "active": True,
                    "synthetic": True,
                }
            },
            buckets={
                BUCKET_ID: {
                    "policy_id": APPROVED_POLICY_ID,
                    "policy_hash": approved_hash,
                    "approved_policy_hash": approved_hash,
                    "bulk_access_allowed": False,
                    "record_count": 25,
                    "synthetic": True,
                }
            },
            exposure={
                BUCKET_ID: {
                    "accessed_record_ids": [],
                    "confirmed_count": 0,
                    "last_outcome": "none",
                }
            },
        )

    @classmethod
    def adverse_fixture(cls) -> "MockCloudState":
        """Return deterministic state after the adverse cloud branch."""

        state = cls.baseline()
        bucket = state.buckets[BUCKET_ID]
        bucket["policy_id"] = ALTERED_POLICY_ID
        bucket["policy_hash"] = _policy_hash(ALTERED_POLICY_ID)
        bucket["bulk_access_allowed"] = True
        record_ids = [f"synthetic-record-{index:03d}" for index in range(1, 26)]
        state.exposure[BUCKET_ID] = {
            "accessed_record_ids": record_ids,
            "confirmed_count": len(record_ids),
            "last_outcome": "full_exposure",
        }
        return state

    def snapshot(self) -> dict[str, Any]:
        """Return a defensive state copy for evidence and readiness checks."""

        return {
            "principals": deepcopy(self.principals),
            "keys": deepcopy(self.keys),
            "buckets": deepcopy(self.buckets),
            "exposure": deepcopy(self.exposure),
        }

    def _capture(self) -> str:
        self._rollback_sequence += 1
        token = f"cloud-rb-{self._rollback_sequence}"
        self._rollbacks[token] = self.snapshot()
        return token

    def revoke_key(self, key_id: str, control: ExecutionControl) -> str:
        """Revoke one allowlisted opaque key identifier."""

        control.checkpoint()
        token = self._capture()
        self.keys[key_id]["active"] = False
        return token

    def disable_principal(self, principal_id: str, control: ExecutionControl) -> str:
        """Disable the principal and atomically revoke each owned mock key."""

        control.checkpoint()
        token = self._capture()
        self.principals[principal_id]["enabled"] = False
        for key in self.keys.values():
            if key["principal_id"] == principal_id:
                key["active"] = False
        return token

    def restore_policy(self, bucket_id: str, control: ExecutionControl) -> str:
        """Restore the approved mock policy and deny bulk retrieval."""

        control.checkpoint()
        token = self._capture()
        bucket = self.buckets[bucket_id]
        bucket["policy_id"] = APPROVED_POLICY_ID
        bucket["policy_hash"] = bucket["approved_policy_hash"]
        bucket["bulk_access_allowed"] = False
        return token

    def access_decision(
        self, principal_id: str, key_id: str, bucket_id: str, *, bulk: bool
    ) -> tuple[bool, str]:
        """Evaluate a future mock request without changing evidence state."""

        principal = self.principals.get(principal_id)
        key = self.keys.get(key_id)
        bucket = self.buckets.get(bucket_id)
        if principal is None:
            reason = "principal_unknown"
        elif key is None:
            reason = "key_unknown"
        elif bucket is None:
            reason = "bucket_unknown"
        elif not principal["enabled"]:
            reason = "principal_disabled"
        elif key["principal_id"] != principal_id:
            reason = "key_principal_mismatch"
        elif not key["active"]:
            reason = "key_revoked"
        elif bulk and not bucket["bulk_access_allowed"]:
            reason = "policy_denied"
        else:
            reason = "allowed"
        return reason == "allowed", reason

    def reset_to_baseline(self, control: ExecutionControl) -> str:
        """Capture the current state and restore the approved fixture."""

        control.checkpoint()
        token = self._capture()
        baseline = self.baseline()
        self.principals = baseline.principals
        self.keys = baseline.keys
        self.buckets = baseline.buckets
        self.exposure = baseline.exposure
        return token

    def readiness_mismatches(self) -> tuple[str, ...]:
        """Return state sections that differ from the approved fixture."""

        baseline = self.baseline().snapshot()
        current = self.snapshot()
        return tuple(
            section
            for section, expected in baseline.items()
            if current[section] != expected
        )

    def rollback(self, token: str, control: ExecutionControl) -> tuple[str, ...]:
        """Restore an exact, one-use pre-action state snapshot."""

        control.checkpoint()
        try:
            snapshot = self._rollbacks.pop(token)
        except KeyError as exc:
            raise ActionExecutionError(
                "invalid_rollback", "Unknown or already-used rollback token"
            ) from exc
        self.principals = snapshot["principals"]
        self.keys = snapshot["keys"]
        self.buckets = snapshot["buckets"]
        self.exposure = snapshot["exposure"]
        return ("restored pre-action mock-cloud state",)


def _no_parameters(parameters: Mapping[str, Any]) -> None:
    if parameters:
        raise ValueError("this action accepts no parameters")


# The complete mutation surface stays together for role/target policy review.
# pylint: disable=too-many-locals
def register_cloud_actions(
    registry: ActionRegistry, state: MockCloudState, *, run_id: str
) -> None:
    """Register cloud containment, reset, and readiness actions."""

    def revoke(_params, target, control):
        token = state.revoke_key(target["id"], control)
        return ActionEffect((f"revoked mock-cloud key {target['id']}",), token)

    def disable(_params, target, control):
        token = state.disable_principal(target["id"], control)
        return ActionEffect((f"disabled mock-cloud principal {target['id']}",), token)

    def restore(_params, target, control):
        token = state.restore_policy(target["id"], control)
        return ActionEffect((f"restored approved policy for {target['id']}",), token)

    def reset(_params, _target, control):
        token = state.reset_to_baseline(control)
        return ActionEffect(("restored approved mock-cloud baseline",), token)

    def readiness(_params, _target, control):
        control.checkpoint()
        mismatches = state.readiness_mismatches()
        if mismatches:
            raise ActionExecutionError(
                "baseline_mismatch",
                "Mock-cloud baseline differs in: " + ", ".join(mismatches),
            )
        return ActionEffect(("validated approved mock-cloud baseline",))

    for action_id, target, handler, rollback_method in (
        (
            "cloud.key.revoke",
            f"cloud_key:{KEY_ID}",
            revoke,
            "restore prior mock key state",
        ),
        (
            "cloud.principal.disable",
            f"cloud_principal:{PRINCIPAL_ID}",
            disable,
            "restore principal and owned key states",
        ),
        (
            "cloud.policy.restore",
            f"cloud_bucket:{BUCKET_ID}",
            restore,
            "restore prior mock bucket policy",
        ),
    ):
        registry.register(
            ActionDefinition(
                action_id=action_id,
                phase="cloud",
                allowed_roles=CLOUD_ROLES,
                allowed_targets=frozenset({target}),
                allowed_run_states=frozenset({"running"}),
                max_timeout_seconds=20,
                expected_effects=(action_id,),
                rollback_method=rollback_method,
                handler=handler,
                rollback_handler=state.rollback,
                parameter_validator=_no_parameters,
            )
        )

    for action_id, phase, states, handler, effect in (
        (
            "exercise.cloud.reset",
            "post_exercise",
            frozenset({"stopped", "resetting"}),
            reset,
            "restore approved mock-cloud baseline",
        ),
        (
            "exercise.cloud.readiness.validate",
            "setup",
            frozenset({"setup", "stopped", "resetting", "ready"}),
            readiness,
            "validate approved mock-cloud baseline",
        ),
    ):
        registry.register(
            ActionDefinition(
                action_id=action_id,
                phase=phase,
                allowed_roles=CONTROL_ROLES,
                allowed_targets=frozenset({f"exercise_run:{run_id}"}),
                allowed_run_states=states,
                max_timeout_seconds=30,
                expected_effects=(effect,),
                rollback_method="restore captured pre-action state",
                handler=handler,
                rollback_handler=state.rollback,
                parameter_validator=_no_parameters,
            )
        )


def build_cloud_adapter(
    *,
    exercise_id: str,
    run_id: str,
    state: MockCloudState,
    run_state: Callable[[str, str], str],
    event_sink: Callable[[Mapping[str, Any]], Any],
) -> SafeActionAdapter:
    """Build a scenario-engine-ready mock-cloud adapter."""

    registry = ActionRegistry()
    register_cloud_actions(registry, state, run_id=run_id)
    return SafeActionAdapter(
        context=EventContext(
            exercise_id=exercise_id,
            run_id=run_id,
            source_kind="action_adapter",
            source_component="mock-cloud-action-adapter",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=run_state,
        event_sink=event_sink,
    )
