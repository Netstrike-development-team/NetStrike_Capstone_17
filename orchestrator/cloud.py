"""Local mock-cloud investigation and reviewed MSEL transitions, never cloud APIs."""

from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from shared.actions import (
    ActionContractError, ActionDefinition, ActionEffect, ActionExecutionError,
    ActionRegistry, SafeActionAdapter, make_action_request,
)
from shared.events import EventBuilder, EventContext, entity

from .checkpoints import CheckpointEvaluation
from .controller import AutomationResult, ControllerError, ItemStatus, RunState


CLOUD_ACTIONS = frozenset({
    "cloud.key.revoke", "cloud.principal.disable", "cloud.policy.restore",
    "cloud.evidence.preserve",
})
CLOUD_SCENARIO_PATH = Path(__file__).resolve().parent / "scenarios" / "cloud-slice.v1.json"
STEPS = {
    "cloud.access.stage": "ACT-05",
    "cloud.policy.expand": "ACT-06",
    "cloud.bulk.verify": "ACT-07A",
    "cloud.bulk.attempt": "ACT-07B",
}


class CloudStage:  # pylint: disable=too-many-instance-attributes
    """Run-owned state, read-only audit, and exact-target action adapters."""

    def __init__(self, run, run_id: str) -> None:
        self.run = run
        self.run_id = run_id
        self.module = importlib.import_module("modules.06-cloud-exfil.cloud_actions")
        self.state = self.module.MockCloudState.baseline()
        self.audit: list[dict[str, Any]] = []
        self.assessment: dict[str, Any] | None = None
        self.access_staged = False
        self.policy_attempted = False
        self._emitted: set[str] = set()
        self._rollbacks: dict[str, Any] = {}
        self._rollback_sequence = 0
        context = EventContext(
            exercise_id=run.definition.exercise_id, run_id=run_id,
            source_kind="module", source_component="mock-cloud-simulator",
            producer_version="1.0.0",
        )
        self.events = EventBuilder(
            context, clock=run.clock, sequence_factory=run.sequencer.next,
        )
        registry = ActionRegistry()
        self.module.register_cloud_actions(
            registry, self.state, run_id=run_id,
            audit_provider=lambda: deepcopy(self.audit),
        )
        self.adapter = self._adapter(registry, "mock-cloud-action-adapter")
        automation_registry = ActionRegistry()
        for action_id, item_id in STEPS.items():
            def execute(_parameters, _target, control, current=action_id):
                return self._transition(current, control)

            automation_registry.register(ActionDefinition(
                action_id=action_id, phase="cloud",
                allowed_roles=frozenset({"scenario_engine"}),
                allowed_targets=frozenset({f"msel_item:{item_id}"}),
                allowed_run_states=frozenset({"running", "paused"})
                if item_id.startswith("ACT-07") else frozenset({"running"}),
                max_timeout_seconds=20, expected_effects=(action_id,),
                rollback_method="restore exact mock-cloud transition state",
                handler=execute, rollback_handler=self._rollback,
                parameter_validator=self._no_parameters,
            ))
        self.automation_adapter = self._adapter(
            automation_registry, "mock-cloud-automation",
        )

    @staticmethod
    def _no_parameters(parameters):
        if parameters:
            raise ValueError("mock-cloud transitions accept no parameters")

    def _adapter(self, registry, component):
        return SafeActionAdapter(
            context=EventContext(
                exercise_id=self.run.definition.exercise_id, run_id=self.run_id,
                source_kind="action_adapter", source_component=component,
                producer_version="1.0.0",
            ),
            registry=registry, run_state=self.run._run_state,  # pylint: disable=protected-access
            event_sink=self.run.event_sink, clock=self.run.clock,
            sequence_factory=self.run.sequencer.next,
        )

    @property
    def handlers(self):
        """Only these four reviewed steps are executable by the controller."""
        return dict.fromkeys(STEPS, self.handle)

    def _capture(self):
        self._rollback_sequence += 1
        token = f"cloud-stage-rb-{self._rollback_sequence}"
        self._rollbacks[token] = (
            self.state.snapshot(), self.access_staged, self.policy_attempted,
        )
        return token

    def _rollback(self, token, control):
        control.checkpoint()
        if token not in self._rollbacks:
            raise ActionExecutionError("invalid_rollback", "Unknown transition snapshot")
        snapshot, self.access_staged, self.policy_attempted = self._rollbacks.pop(token)
        for name, value in snapshot.items():
            setattr(self.state, name, value)
        return ("restored exact mock-cloud transition state",)

    def _decision(self, *, bulk):
        return self.state.access_decision(
            self.module.PRINCIPAL_ID, self.module.KEY_ID, self.module.BUCKET_ID,
            bulk=bulk,
        )

    def _read_records(self, count):
        exposure = self.state.exposure[self.module.BUCKET_ID]
        records = sorted(self.state.objects)[:count]
        exposure.update(
            accessed_record_ids=records, confirmed_count=len(records),
            last_outcome="full_exposure" if count == 25 else "sample_access",
        )

    def _transition(self, action_id, control):
        control.checkpoint()
        if action_id != "cloud.access.stage" and not self.access_staged:
            raise ActionExecutionError("cloud_not_staged", "Cloud access must be staged first")
        if action_id.startswith("cloud.bulk.") and not self.policy_attempted:
            raise ActionExecutionError(
                "policy_not_attempted", "Policy step must precede bulk attempt",
            )
        if action_id.startswith("cloud.bulk."):
            expected = "pass" if action_id == "cloud.bulk.verify" else "miss"
            if self.run.controller.checkpoint_results.get("DP3") != expected:
                raise ActionExecutionError("branch_not_verified", "Resolve DP3 before its branch")
        token = self._capture()
        allowed, _reason = self._decision(bulk=False)
        if action_id == "cloud.access.stage":
            self.access_staged = True
            if allowed:
                self._read_records(1)
        elif action_id == "cloud.policy.expand":
            self.policy_attempted = True
            if allowed:
                bucket = self.state.buckets[self.module.BUCKET_ID]
                altered = self.module.MockCloudState.adverse_fixture().buckets[
                    self.module.BUCKET_ID
                ]
                bucket.update(
                    policy_id=altered["policy_id"], policy_hash=altered["policy_hash"],
                    bulk_access_allowed=True,
                )
                self._read_records(5)
        elif action_id in {"cloud.bulk.verify", "cloud.bulk.attempt"}:
            allowed, _reason = self._decision(bulk=True)
            if action_id == "cloud.bulk.verify" and allowed:
                raise ActionExecutionError(
                    "containment_mismatch", "Bulk request is unexpectedly allowed",
                )
            if allowed:
                self._read_records(25)
            else:
                self.state.exposure[self.module.BUCKET_ID]["last_outcome"] = "bulk_blocked"
        return ActionEffect((f"completed reviewed mock step {action_id}",), token)

    def _emit(self, event_type, operation, message, *, allowed=True, data=None):
        event = self.events.build(
            event_type=event_type, phase="cloud",
            actor=entity("cloud_principal", self.module.PRINCIPAL_ID),
            action=operation, target=entity("cloud_bucket", self.module.BUCKET_ID),
            outcome_status="success" if allowed else "blocked",
            message=message, visibility="participant", dry_run=False,
            safety_controls=("synthetic-data", "local-mock", "allowlisted-target"),
            objective_ids=("LO3",),
            correlation_ids=(self.module.PRINCIPAL_ID, self.module.KEY_ID, self.module.BUCKET_ID),
            data={
                "host": "CLOUD01", "principal_id": self.module.PRINCIPAL_ID,
                "key_id": self.module.KEY_ID, "bucket_id": self.module.BUCKET_ID,
                "source_ip": "203.0.113.77", "synthetic": True,
                "external_transfer_observed": False,
                **dict(data or {}),
            },
        )
        self.run.event_sink(event)
        self.audit.append(deepcopy(event))

    def _evidence(self, action_id):
        exposure = self.state.exposure[self.module.BUCKET_ID]
        if action_id == "cloud.access.stage":
            allowed, reason = self._decision(bulk=False)
            self._emit(
                "cloud.authentication.succeeded" if allowed else "cloud.authentication.blocked",
                "cloud.authenticate", "Mock service-key authentication evaluated",
                allowed=allowed, data={"reason": reason},
            )
            if allowed:
                self._emit("cloud.bucket.enumerated", "cloud.bucket.list",
                           "Mock storage enumeration completed",
                           data={"buckets": [self.module.BUCKET_ID]})
        elif action_id == "cloud.policy.expand":
            allowed, reason = self._decision(bulk=False)
            bucket = self.state.buckets[self.module.BUCKET_ID]
            self._emit(
                "cloud.policy.changed" if allowed else "cloud.policy.change_blocked",
                "cloud.policy.change", "Mock bucket policy change evaluated",
                allowed=allowed, data={
                    "reason": reason, "old_policy_id": self.module.APPROVED_POLICY_ID,
                    "new_policy_id": bucket["policy_id"], "policy_hash": bucket["policy_hash"],
                    "approved_policy_hash": bucket["approved_policy_hash"],
                },
            )
        else:
            allowed, reason = self._decision(bulk=True)
            self._emit(
                "cloud.bulk_access.completed" if allowed else "cloud.bulk_access.blocked",
                "cloud.object.bulk_read", "Mock bulk retrieval evaluated against current controls",
                allowed=allowed, data={
                    "reason": reason, "confirmed_count": exposure["confirmed_count"],
                },
            )
            if allowed:
                self._emit("cloud.extortion.claimed", "cloud.extortion.claim",
                           "Synthetic threat message claims theft of the customer export",
                           data={"claim_only": True, "claimed_records": 25})
        self._emit(
            "cloud.object.accessed", "cloud.object.review",
            "Cumulative confirmed synthetic object access",
            data={
                "record_ids": exposure["accessed_record_ids"],
                "confirmed_count": exposure["confirmed_count"],
                "bytes": exposure["confirmed_count"] * 200,
            },
        )

    def handle(self, item, run_id):
        """Execute one correlated allowlisted step, once, with canonical evidence."""
        with self.run.state_lock:
            return self._handle_locked(item, run_id)

    def _handle_locked(self, item, run_id):
        if run_id != self.run_id or STEPS.get(item.action_id) != item.item_id:
            return AutomationResult(False, "cloud MSEL/run correlation mismatch")
        request = make_action_request(
            exercise_id=self.run.definition.exercise_id, run_id=run_id,
            actor=entity("service_account", "scenario-engine", role="scenario_engine"),
            action_id=item.action_id, target=entity("msel_item", item.item_id),
            idempotency_key=f"{run_id}:{item.item_id}", timeout_seconds=20,
            dry_run=False,
            clock=self.run.clock,
        )
        result = self.automation_adapter.execute(request)
        if not result["successful"]:
            return AutomationResult(False, result["message"], {"error_code": result["error_code"]})
        if item.item_id not in self._emitted:
            self._evidence(item.action_id)
            self._emitted.add(item.item_id)
        return AutomationResult(True, "Reviewed mock-cloud operation completed",
                                {"action_request_id": result["request_id"]})

    def view(self):
        """Only observed/current cloud facts, never scores or branch criteria."""
        with self.run.state_lock:
            return {
                "exercise_id": self.run.definition.exercise_id, "run_id": self.run_id,
                "mock": True, "state": self.state.snapshot(), "audit": deepcopy(self.audit),
            }

    def submit_assessment(self, *, principal_id, confirmed_count, conclusion, evidence_ids):
        """Store a bounded claim backed by actual current-run cloud event IDs."""
        if self.run.controller.state != RunState.RUNNING or not self.access_staged:
            raise ActionContractError("cloud assessment requires an active staged cloud run")
        valid_ids = {event["event_id"] for event in self.audit}
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ActionContractError("provide unique cloud audit event references")
        if len(evidence_ids) > 20 or not set(evidence_ids) <= valid_ids:
            raise ActionContractError("evidence references must belong to this run's cloud audit")
        if (not isinstance(confirmed_count, int) or isinstance(confirmed_count, bool)
                or not 0 <= confirmed_count <= 25):
            raise ActionContractError("confirmed_count must be an integer from 0 to 25")
        if conclusion not in {"mock_access_only", "external_transfer_proven", "unknown"}:
            raise ActionContractError("unsupported exposure conclusion")
        self.assessment = {
            "principal_id": principal_id, "confirmed_count": confirmed_count,
            "conclusion": conclusion, "evidence_ids": list(evidence_ids),
        }

    def evaluate(self) -> CheckpointEvaluation:
        """DP3 uses current authoritative state and submitted exposure evidence."""
        with self.run.state_lock:
            return self._evaluate_locked()

    def _evaluate_locked(self) -> CheckpointEvaluation:
        bucket = self.state.buckets[self.module.BUCKET_ID]
        assessment = self.assessment or {}
        checks = {
            "cloud_steps_observed": self.access_staged and self.policy_attempted,
            "principal_identified": assessment.get("principal_id") == self.module.PRINCIPAL_ID,
            "key_revoked": self.state.keys[self.module.KEY_ID]["active"] is False,
            "approved_policy_restored": (
                bucket["policy_hash"] == bucket["approved_policy_hash"]
                and bucket["policy_id"] == self.module.APPROVED_POLICY_ID
                and bucket["bulk_access_allowed"] is False
            ),
            "exposure_count_supported": assessment.get("confirmed_count") == (
                self.state.exposure[self.module.BUCKET_ID]["confirmed_count"]
            ),
            "transfer_not_overclaimed": assessment.get("conclusion") == "mock_access_only",
            "exposure_evidence_cited": any(
                event["event_type"] == "cloud.object.accessed"
                and event["event_id"] in assessment.get("evidence_ids", [])
                and event["data"]["confirmed_count"] == assessment.get("confirmed_count")
                for event in self.audit
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return CheckpointEvaluation(
            passed=all(checks.values()),
            reason="Cloud containment and evidenced assessment verified" if not failed
            else "Missing cloud checkpoint requirements: " + ", ".join(failed),
            evidence_ids=tuple(assessment.get("evidence_ids", [])), checks=checks,
        )

    def resolve(self):
        """Prevent early/manual branch selection or a technical fault being scored."""
        controller = self.run.controller
        if controller.items.get("DP3") is None:
            raise ControllerError("selected scenario has no cloud checkpoint")
        if controller.items["DP3"].status != ItemStatus.READY:
            raise ControllerError("DP3 must be due before evaluation")
        if (not self.access_staged or not self.policy_attempted or any(
            controller.items[item_id].status != ItemStatus.DELIVERED
            for item_id in ("ACT-05", "ACT-06")
        )):
            raise ControllerError("cloud source steps incomplete; pause and investigate")
        if any(
            controller.items[item_id].status != ItemStatus.PENDING
            for item_id in ("ACT-07A", "ACT-07B")
        ):
            raise ControllerError("cloud branch unavailable; pause and record the deviation")
        result = self.evaluate()
        controller.resolve_checkpoint(
            "DP3", passed=result.passed, evidence_ids=result.evidence_ids, reason=result.reason,
            checks=result.checks,
        )
        return result
