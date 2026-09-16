"""Deterministic endpoint/AD state and safe-action registrations."""

from __future__ import annotations

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

RESPONDER_ROLES = frozenset({"endpoint_responder", "facilitator"})
CONTROL_ROLES = frozenset({"technical_operator", "facilitator"})


@dataclass
class EndpointAdState:
    """Run-scoped simulation state; no real host or directory is mutated."""

    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    processes: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollbacks: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollback_sequence: int = 0

    @classmethod
    def baseline(cls) -> "EndpointAdState":
        """Return the deterministic clean endpoint/directory baseline."""

        return cls(
            hosts={
                "FIN-WS01": {
                    "isolated": False,
                    "remote_path_enabled": True,
                    "controller_visible": True,
                }
            },
            accounts={
                "svc-print-sync": {
                    "exists": False,
                    "enabled": False,
                    "groups": [],
                }
            },
            processes={"impact-task-01": {"active": False, "host_id": "FIN-WS01"}},
            artifacts={
                "FIN-WS01-discovery-bundle": {
                    "preserved": False,
                    "sha256": "2fdb12a705aa08f08c23e57b57c3ba6657ea7825efcbd24066fded92d95f9ea5",
                    "host_id": "FIN-WS01",
                }
            },
        )

    @classmethod
    def adverse_fixture(cls) -> "EndpointAdState":
        """Return deterministic state after the adverse DP2 branch."""

        state = cls.baseline()
        state.accounts["svc-print-sync"] = {
            "exists": True,
            "enabled": True,
            "groups": ["SimCorp-Server-Operators"],
        }
        state.processes["impact-task-01"]["active"] = True
        return state

    def snapshot(self) -> dict[str, Any]:
        """Return a defensive state copy for reset/readiness evidence."""

        return {
            "hosts": deepcopy(self.hosts),
            "accounts": deepcopy(self.accounts),
            "processes": deepcopy(self.processes),
            "artifacts": deepcopy(self.artifacts),
        }

    def _capture(self) -> str:
        self._rollback_sequence += 1
        token = f"endpoint-rb-{self._rollback_sequence}"
        self._rollbacks[token] = self.snapshot()
        return token

    def isolate_host(self, host_id: str, control: ExecutionControl) -> str:
        """Disable only the simulated remote path while retaining control visibility."""

        control.checkpoint()
        token = self._capture()
        host = self.hosts[host_id]
        host["isolated"] = True
        host["remote_path_enabled"] = False
        host["controller_visible"] = True
        return token

    def preserve_artifact(self, artifact_id: str, control: ExecutionControl) -> str:
        """Mark the predefined evidence bundle preserved without altering source data."""

        control.checkpoint()
        token = self._capture()
        self.artifacts[artifact_id]["preserved"] = True
        return token

    def disable_account(self, account_id: str, control: ExecutionControl) -> str:
        """Disable the predefined adverse-branch directory account."""

        control.checkpoint()
        if not self.accounts[account_id]["exists"]:
            raise ActionExecutionError(
                "target_not_present", "Persistence account is absent"
            )
        token = self._capture()
        self.accounts[account_id]["enabled"] = False
        return token

    def remove_persistence(self, account_id: str, control: ExecutionControl) -> str:
        """Remove the synthetic account and its simulated group memberships."""

        control.checkpoint()
        token = self._capture()
        self.accounts[account_id] = {"exists": False, "enabled": False, "groups": []}
        return token

    def stop_process(self, process_id: str, control: ExecutionControl) -> str:
        """Stop the predefined simulated impact process."""

        control.checkpoint()
        token = self._capture()
        self.processes[process_id]["active"] = False
        return token

    def reset_to_baseline(self, control: ExecutionControl) -> str:
        """Capture current state and restore the clean deterministic fixture."""

        control.checkpoint()
        token = self._capture()
        baseline = self.baseline()
        self.hosts = baseline.hosts
        self.accounts = baseline.accounts
        self.processes = baseline.processes
        self.artifacts = baseline.artifacts
        return token

    def readiness_mismatches(self) -> tuple[str, ...]:
        """Return state sections that differ from the clean baseline."""

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
        self.hosts = snapshot["hosts"]
        self.accounts = snapshot["accounts"]
        self.processes = snapshot["processes"]
        self.artifacts = snapshot["artifacts"]
        return ("restored pre-action endpoint/AD state",)


def _no_parameters(parameters: Mapping[str, Any]) -> None:
    if parameters:
        raise ValueError("this action accepts no parameters")


# Definitions remain together so reviewers can audit the entire mutation
# surface, including exact roles, targets, and run states.
# pylint: disable=too-many-locals
def register_endpoint_actions(
    registry: ActionRegistry, state: EndpointAdState, *, run_id: str
) -> None:
    """Register endpoint/AD containment, reset, and readiness actions."""

    def isolate(_params, target, control):
        token = state.isolate_host(target["id"], control)
        return ActionEffect((f"isolated remote path for {target['id']}",), token)

    def preserve(_params, target, control):
        token = state.preserve_artifact(target["id"], control)
        return ActionEffect((f"preserved evidence {target['id']}",), token)

    def disable(_params, target, control):
        token = state.disable_account(target["id"], control)
        return ActionEffect((f"disabled directory account {target['id']}",), token)

    def remove(_params, target, control):
        token = state.remove_persistence(target["id"], control)
        return ActionEffect((f"removed persistence {target['id']}",), token)

    def stop(_params, target, control):
        token = state.stop_process(target["id"], control)
        return ActionEffect((f"stopped simulated process {target['id']}",), token)

    def reset(_params, _target, control):
        token = state.reset_to_baseline(control)
        return ActionEffect(("restored endpoint/AD baseline",), token)

    def readiness(_params, _target, control):
        control.checkpoint()
        mismatches = state.readiness_mismatches()
        if mismatches:
            raise ActionExecutionError(
                "baseline_mismatch",
                "Endpoint/AD baseline differs in: " + ", ".join(mismatches),
            )
        return ActionEffect(("validated endpoint/AD baseline",))

    definitions = (
        ("endpoint.host.isolate", "host:FIN-WS01", isolate, "endpoint_ad"),
        (
            "evidence.artifact.preserve",
            "evidence_artifact:FIN-WS01-discovery-bundle",
            preserve,
            "endpoint_ad",
        ),
        (
            "ad.account.disable",
            "directory_account:svc-print-sync",
            disable,
            "endpoint_ad",
        ),
        (
            "ad.persistence.remove",
            "directory_account:svc-print-sync",
            remove,
            "endpoint_ad",
        ),
        ("endpoint.process.stop", "process:impact-task-01", stop, "impact_recovery"),
    )
    for action_id, target, handler, phase in definitions:
        registry.register(
            ActionDefinition(
                action_id=action_id,
                phase=phase,
                allowed_roles=RESPONDER_ROLES,
                allowed_targets=frozenset({target}),
                allowed_run_states=frozenset({"running"}),
                max_timeout_seconds=20,
                expected_effects=(action_id,),
                rollback_method="restore captured pre-action state",
                handler=handler,
                rollback_handler=state.rollback,
                parameter_validator=_no_parameters,
            )
        )

    for action_id, phase, states, handler, effect in (
        (
            "exercise.endpoint.reset",
            "post_exercise",
            frozenset({"stopped", "resetting"}),
            reset,
            "restore endpoint/AD baseline",
        ),
        (
            "exercise.endpoint.readiness.validate",
            "setup",
            frozenset({"setup", "stopped", "resetting", "ready"}),
            readiness,
            "validate endpoint/AD baseline",
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


def build_endpoint_adapter(
    *,
    exercise_id: str,
    run_id: str,
    state: EndpointAdState,
    run_state: Callable[[str, str], str],
    event_sink: Callable[[Mapping[str, Any]], Any],
) -> SafeActionAdapter:
    """Build a scenario-engine-ready endpoint/AD adapter."""

    registry = ActionRegistry()
    register_endpoint_actions(registry, state, run_id=run_id)
    return SafeActionAdapter(
        context=EventContext(
            exercise_id=exercise_id,
            run_id=run_id,
            source_kind="action_adapter",
            source_component="endpoint-ad-action-adapter",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=run_state,
        event_sink=event_sink,
    )
