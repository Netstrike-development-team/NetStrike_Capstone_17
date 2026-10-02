"""Reviewed impact/recovery play over explicitly approved disposable fixtures."""

from __future__ import annotations

import importlib
import time
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

FULL_SCENARIO_PATH = Path(__file__).resolve().parent / "scenarios" / "full-play.v1.json"
RECOVERY_ACTIONS = frozenset({"recovery.fixture.restore", "recovery.health.validate"})
ROOT_MARKER = ".netstrike-disposable-root"
ROOT_CONTENT = b"NETSTRIKE DISPOSABLE IMPACT ROOT v1\n"
STEPS = {
    "impact.fixture.prepare": "PRE-03",
    "impact.business.notice": "MSEL-08",
    "impact.branch.blocked": "ACT-08A",
    "impact.branch.realized": "ACT-08B",
    "exercise.play.finish": "END-01",
}


class ImpactStage:  # pylint: disable=too-many-instance-attributes
    """Own only one run's five decoys, local evidence and recovery review."""

    def __init__(self, run, run_id, approved_root, *, fixture=None):
        self.run = run
        self.run_id = run_id
        self.module = importlib.import_module("modules.07-ransomware-sim.impact_actions")
        if not approved_root:
            raise ValueError("full-play scenario requires NETSTRIKE_IMPACT_ROOT")
        if not self.module.RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("impact run id must be a safe directory identifier")
        self.root = self._approved_root(approved_root)
        self.fixture = fixture or self.module.ImpactFixture.provision(self.root, run_id)
        self.prepared = False
        self.applied = False
        self.audit: list[dict[str, Any]] = []
        self.brief: dict[str, Any] | None = None
        self.validation_event_id: str | None = None
        self.last_impact_request: str | None = None
        self.final_review: CheckpointEvaluation | None = None
        self._emitted: set[str] = set()
        self.events = EventBuilder(
            EventContext(
                exercise_id=run.definition.exercise_id, run_id=run_id,
                source_kind="module", source_component="marker-impact-simulator",
                producer_version="1.0.0",
            ),
            clock=run.clock, sequence_factory=run.sequencer.next,
        )
        registry = ActionRegistry()
        self.module.register_impact_actions(registry, self.fixture, run_id=run_id)
        self.adapter = self._adapter(registry, "marker-impact-action-adapter")
        automation = ActionRegistry()
        for action_id, item_id in STEPS.items():
            if item_id.startswith("ACT-08"):
                continue
            def execute(_parameters, _target, control, current=action_id):
                return self._transition(current, control)
            automation.register(ActionDefinition(
                action_id=action_id, phase="impact_recovery",
                allowed_roles=frozenset({"scenario_engine"}),
                allowed_targets=frozenset({f"msel_item:{item_id}"}),
                allowed_run_states=frozenset({"ready"})
                if item_id == "PRE-03" else frozenset({"running"}),
                max_timeout_seconds=20, expected_effects=(action_id,),
                rollback_method="full run reset restores preparation state",
                handler=execute, rollback_handler=lambda _token, _control: (),
                parameter_validator=self._no_parameters,
            ))
        self.automation_adapter = self._adapter(automation, "marker-impact-automation")

    @staticmethod
    def _no_parameters(parameters):
        if parameters:
            raise ValueError("reviewed impact steps accept no parameters")

    def _approved_root(self, value):
        root = Path(value)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("impact root must be an existing absolute real directory")
        root = root.resolve(strict=True)
        if root in {Path("/"), Path.home(), Path(__file__).resolve().parents[1]}:
            raise ValueError("impact root must be a dedicated disposable directory")
        marker = root / ROOT_MARKER
        if marker.exists() or marker.is_symlink():
            if (marker.is_symlink() or not marker.is_file()
                    or marker.stat().st_nlink != 1 or marker.stat().st_size != len(ROOT_CONTENT)
                    or marker.read_bytes() != ROOT_CONTENT):
                raise ValueError("impact root ownership marker is invalid")
        else:
            if any(root.iterdir()):
                raise ValueError("new impact root must be empty; unrelated files are not permitted")
            with marker.open("xb") as marker_file:
                marker_file.write(ROOT_CONTENT)
        for child in root.iterdir():
            if child.name == ROOT_MARKER:
                continue
            if (not self.module.RUN_ID_PATTERN.fullmatch(child.name)
                    or child.is_symlink() or not child.is_dir()
                    or {entry.name for entry in child.iterdir()}
                    != {"live", "known-good", "staging"}):
                raise ValueError("impact root contains an unapproved entry")
        return root

    def _adapter(self, registry, component, *, reset_control=False):
        def run_state(_exercise, _run):
            state = self.run.controller.state.value
            return "stopped" if reset_control and state == "completed" else state
        return SafeActionAdapter(
            context=EventContext(
                exercise_id=self.run.definition.exercise_id, run_id=self.run_id,
                source_kind="action_adapter", source_component=component,
                producer_version="1.0.0",
            ),
            registry=registry, run_state=run_state, event_sink=self.run.event_sink,
            clock=self.run.clock, sequence_factory=self.run.sequencer.next,
        )

    @property
    def handlers(self):
        """The reviewed MSEL is the only attacker-side delivery surface."""
        return dict.fromkeys(STEPS, self.handle)

    def _emit(self, event_type, message, *, data=None, visibility="participant"):
        event = self.events.build(
            event_type=event_type, phase="impact_recovery",
            actor=entity("service_account", "scenario-engine", role="scenario_engine"),
            action=event_type, target=entity("fixture_set", self.module.FIXTURE_ID),
            outcome_status="success", message=message, visibility=visibility,
            dry_run=False, objective_ids=("LO4", "LO5"),
            safety_controls=("synthetic-data", "allowlisted-fixture", "no-encryption"),
            data={"host": "FILE01", "encryption_performed": False, **dict(data or {})},
        )
        self.run.event_sink(event)
        if visibility == "participant":
            self.audit.append(deepcopy(event))
        return event

    def _transition(self, action_id, control):
        control.checkpoint()
        if action_id == "impact.fixture.prepare":
            if self.fixture.health_mismatches():
                raise ActionExecutionError("fixture_unhealthy", "Disposable baseline is not ready")
            self.run.endpoint_state.processes["impact-task-01"]["active"] = True
            self.prepared = True
            return ActionEffect(("validated decoys and armed the synthetic pre-staged task",))
        if action_id == "impact.business.notice":
            if "DP3" not in self.run.controller.checkpoint_results:
                raise ActionExecutionError("cloud_not_resolved", "Resolve cloud checkpoint first")
            branch = (
                "ACT-07A" if self.run.controller.checkpoint_results["DP3"] == "pass"
                else "ACT-07B"
            )
            if self.run.controller.items[branch].status != ItemStatus.DELIVERED:
                raise ActionExecutionError(
                    "cloud_outcome_missing", "Cloud outcome unobserved; notification blocked",
                )
            count = self.run.cloud.state.exposure[
                self.run.cloud.module.BUCKET_ID
            ]["confirmed_count"]
            claim = any(e["event_type"] == "cloud.extortion.claimed" for e in self.run.cloud.audit)
            message = (
                "A synthetic threat message claims theft; verify against the mock audit."
                if claim else "The later mock bulk request was blocked; verify residual scope."
            )
            return ActionEffect((message,), metadata={"confirmed_records": count})
        if action_id == "exercise.play.finish":
            if self.run.controller.elapsed_seconds < 7800:
                raise ActionExecutionError("end_not_due", "Play ends at 130 minutes")
            if not self.applied or any(
                checkpoint not in self.run.controller.checkpoint_results
                for checkpoint in ("DP1", "DP2", "DP3", "DP4")
            ):
                raise ActionExecutionError(
                    "observation_incomplete", "Required source/checkpoint missing",
                )
            required_sources = [
                "PRE-01", "PRE-02", "PRE-03", "ACT-01", "ACT-02", "ACT-03",
                "ACT-05", "ACT-06", "MSEL-08",
                "ACT-04A" if self.run.controller.checkpoint_results["DP2"] == "pass" else "ACT-04B",
                "ACT-07A" if self.run.controller.checkpoint_results["DP3"] == "pass" else "ACT-07B",
            ]
            if any(self.run.controller.items[item].status != ItemStatus.DELIVERED
                   for item in required_sources):
                raise ActionExecutionError(
                    "source_evidence_missing", "Source failed or skipped; pause and investigate",
                )
            branch = (
                "ACT-08A" if self.run.controller.checkpoint_results["DP4"] == "pass"
                else "ACT-08B"
            )
            if self.run.controller.items[branch].status != ItemStatus.DELIVERED:
                raise ActionExecutionError(
                    "impact_evidence_missing", "Impact source failed; pause and investigate",
                )
            self.final_review = self.evaluate_recovery()
            return ActionEffect(("Play ended; recovery/brief observations frozen for evaluation",))
        raise ActionExecutionError("unregistered_step", "Unknown impact step")

    # Correlation/target/role/preview fields remain explicit at this audit boundary.
    # pylint: disable=too-many-arguments
    def _request(self, action_id, target, actor, key, *, parameters=None, dry_run=True):
        return make_action_request(
            exercise_id=self.run.definition.exercise_id, run_id=self.run_id,
            actor=actor, action_id=action_id, target=target, idempotency_key=key,
            parameters=parameters, dry_run=dry_run, timeout_seconds=15,
            clock=self.run.clock,
        )

    def handle(self, item, run_id):
        """Guard correlation, deadline and branch truth before touching decoys."""
        with self.run.state_lock:
            if run_id != self.run_id or STEPS.get(item.action_id) != item.item_id:
                return AutomationResult(False, "impact MSEL/run correlation mismatch")
            actor = entity("service_account", "scenario-engine", role="scenario_engine")
            if item.item_id.startswith("ACT-08"):
                expected = "pass" if item.item_id == "ACT-08A" else "miss"
                if self.run.controller.checkpoint_results.get("DP4") != expected:
                    return AutomationResult(False, "Resolve DP4 before its branch")
                if not self.prepared:
                    return AutomationResult(False, "Impact source is not prepared")
                # A stopped local task stays stopped even if another checkpoint
                # requirement missed. Isolation alone cannot stop a pre-staged task.
                variant = "realized" if self.run.endpoint_state.processes[
                    "impact-task-01"
                ]["active"] else "blocked"
                request = self._request(
                    "impact.marker.apply", entity("fixture_set", self.module.FIXTURE_ID),
                    actor, f"{run_id}:{item.item_id}",
                    parameters={"variant": variant}, dry_run=False,
                )
                result = self.adapter.execute(request)
            else:
                request = self._request(
                    item.action_id, entity("msel_item", item.item_id),
                    actor, f"{run_id}:{item.item_id}", dry_run=False,
                )
                result = self.automation_adapter.execute(request)
            if not result["successful"]:
                return AutomationResult(
                    False, result["message"], {"error_code": result["error_code"]},
                )
            if item.item_id not in self._emitted:
                if item.item_id.startswith("ACT-08"):
                    self.applied = True
                    self.last_impact_request = result["request_id"]
                    self.validation_event_id = None
                    self._emit("impact.markers.applied", "Marker-only exercise impact evaluated",
                               data=self.fixture.inspect())
                elif item.item_id == "PRE-03":
                    self._emit("impact.fixture.prepared", "Disposable recovery baseline prepared",
                               data=self.fixture.inspect())
                    self._emit(
                        "impact.task.armed", "Pre-staged synthetic task available for containment",
                        data={"task_id": "impact-task-01", "active": True},
                    )
                elif item.item_id == "END-01":
                    self._emit("recovery.review.completed", "Recovery and brief review frozen",
                               visibility="evaluator", data={
                                   "passed": self.final_review.passed,
                                   "checks": self.final_review.checks,
                                   "evidence_ids": list(self.final_review.evidence_ids),
                                   "report_quality_requires_evaluator": True,
                               })
                self._emitted.add(item.item_id)
            message = (
                result["effects"][0] if item.item_id == "MSEL-08"
                else "Reviewed impact/recovery step completed"
            )
            return AutomationResult(True, message, {"action_request_id": result["request_id"]})

    def prevention(self):
        """DP4 prevention state; no communication/recovery claims are invented."""
        endpoint = self.run.endpoint_state
        account = endpoint.accounts["svc-print-sync"]
        host = endpoint.hosts["FIN-WS01"]
        checks = {
            "source_prepared": self.prepared,
            "host_isolated": host["isolated"] and not host["remote_path_enabled"],
            "persistence_removed": not account["exists"] and not account["groups"],
            "impact_task_disabled": endpoint.processes["impact-task-01"]["active"] is False,
        }
        return self._evaluation(checks)

    @staticmethod
    def _evaluation(checks, evidence=()):
        failed = [name for name, passed in checks.items() if not passed]
        return CheckpointEvaluation(
            passed=all(checks.values()), checks=checks, evidence_ids=tuple(evidence),
            reason="Required impact/recovery observations verified" if not failed
            else "Missing observations: " + ", ".join(failed),
        )

    def resolve(self):
        """Staff may resolve DP4 only with a healthy, prepared, due source."""
        with self.run.state_lock:
            controller = self.run.controller
            if controller.state != RunState.RUNNING:
                raise ControllerError("resume play before resolving the impact branch")
            if controller.items["DP4"].status != ItemStatus.READY:
                raise ControllerError("DP4 must be due before evaluation")
            if (not self.prepared or controller.items["PRE-03"].status != ItemStatus.DELIVERED
                    or self.fixture.health_mismatches()):
                raise ControllerError("Impact source not ready; pause and investigate")
            if any(controller.items[item].status != ItemStatus.PENDING
                   for item in ("ACT-08A", "ACT-08B")):
                raise ControllerError("Impact branch unavailable; record the deviation")
            if any(dp not in controller.checkpoint_results for dp in ("DP2", "DP3")):
                raise ControllerError("Resolve earlier containment checkpoints first")
            result = self.prevention()
            controller.resolve_checkpoint(
                "DP4", passed=result.passed, reason=result.reason,
                evidence_ids=("state:host:FIN-WS01", "state:process:impact-task-01"),
                checks=result.checks,
            )
            return result

    def view(self):
        """Read-only current hashes, task/control state and observed audit."""
        with self.run.state_lock:
            return {
                "exercise_id": self.run.definition.exercise_id, "run_id": self.run_id,
                "fixture": self.fixture.inspect(), "audit": deepcopy(self.audit),
                "endpoint": self.run.endpoint_state.snapshot(),
            }

    def staff_state(self):
        """Keep stop/reset controls usable even when filesystem safety checks fail."""
        def result(value):
            return {
                "passed": value.passed, "reason": value.reason,
                "checks": value.checks, "evidence_ids": list(value.evidence_ids),
            }
        try:
            return {
                "enabled": True, "view": self.view(),
                "dp4_preview": result(self.prevention()),
                "recovery_preview": result(self.evaluate_recovery()),
                "final_review": result(self.final_review) if self.final_review else None,
                "rollback_available": bool(self.last_impact_request),
            }
        except (ActionExecutionError, ValueError, OSError):
            return {
                "enabled": True, "health_error": "unsafe_or_unreadable_fixture",
                "dp4_preview": result(self.prevention()),
                "recovery_preview": result(self._evaluation({"fixture_safe": False})),
                "final_review": None, "rollback_available": False,
            }

    def recover(self, *, actor, action_id, fixture_id, key, dry_run=True):
        """Preview by default; only exact fixture IDs and recovery roles can write."""
        with self.run.state_lock:
            if action_id not in RECOVERY_ACTIONS or not self.applied:
                raise ActionContractError("recovery requires an observed impact branch")
            request = self._request(
                action_id, entity("fixture_set", fixture_id), actor, key, dry_run=dry_run,
            )
            result = self.adapter.execute(request)
            if result["successful"] and not dry_run and not result["cached"]:
                event_type = (
                    "recovery.fixture.restored" if action_id == "recovery.fixture.restore"
                    else "recovery.health.verified"
                )
                event = self._emit(event_type, "Disposable fixture recovery observation",
                                   data=self.fixture.inspect())
                self.validation_event_id = (
                    event["event_id"] if action_id == "recovery.health.validate" else None
                )
            return result

    def rollback(self, actor):
        """Only the current run's successful impact request is rollback-capable here."""
        with self.run.state_lock:
            if not self.last_impact_request:
                raise ActionContractError("no successful impact is available for rollback")
            effects = self.adapter.rollback(self.last_impact_request, actor)
            self.last_impact_request = None
            self.validation_event_id = None
            self._emit("impact.rollback.completed", "Staff restored the pre-impact decoys",
                       data=self.fixture.inspect())
            return {"effects": list(effects), "run_id": self.run_id}

    def submit_brief(self, payload):
        """Retain five communication sections with genuine current-run references."""
        with self.run.state_lock:
            if self.run.controller.state != RunState.RUNNING or not self.applied:
                raise ActionContractError("brief requires active recovery play")
            references = payload["evidence_ids"]
            allowed = {event["event_id"] for event in self.audit}
            if (not references or len(set(references)) != len(references)
                    or not set(references) <= allowed):
                raise ActionContractError(
                    "brief references must be unique current-run impact evidence",
                )
            self.brief = deepcopy(payload)

    def evaluate_recovery(self):
        """Observe recovery and report completeness; quality/rubric stays with #84."""
        with self.run.state_lock:
            status = self.fixture.inspect()
            brief = self.brief or {}
            count = self.run.cloud.state.exposure[
                self.run.cloud.module.BUCKET_ID
            ]["confirmed_count"]
            checks = {
                "originals_unchanged": status["originals_unchanged"] and status["backup_intact"],
                "baseline_restored": status["baseline_verified"],
                "health_validation_recorded": bool(self.validation_event_id),
                "health_evidence_cited": self.validation_event_id in brief.get("evidence_ids", [])
                if self.validation_event_id else False,
                "scope_count_supported": brief.get("confirmed_cloud_records") == count,
                "communication_sections_present": all(
                    isinstance(brief.get(section), str) and brief[section].strip()
                    for section in (
                        "confirmed_scope", "business_impact", "actions_taken", "remaining_risk",
                    )
                ) and len(brief.get("recommendations", [])) >= 2,
            }
            return self._evaluation(checks, brief.get("evidence_ids", []))

    def validate_next_run(self, run_id):
        """Reject unsafe/reused destinations before restoring or changing the run."""
        self._approved_root(self.root)
        if not self.module.RUN_ID_PATTERN.fullmatch(run_id):
            raise ActionContractError("new impact run id is unsafe")
        destination = self.root / run_id
        if destination.exists() or destination.is_symlink():
            raise ActionContractError("new impact run directory already exists")

    def restore_for_reset(self):
        """Fresh control-only adapter allows explicit cleanup after emergency stop."""
        if self.run.controller.state not in {RunState.STOPPED, RunState.COMPLETED}:
            raise ActionContractError("stop or finish the run before fixture reset")
        registry = ActionRegistry()
        self.module.register_impact_actions(registry, self.fixture, run_id=self.run_id)
        reset_adapter = self._adapter(registry, "impact-reset-controller", reset_control=True)
        request = self._request(
            "exercise.impact.reset", entity("exercise_run", self.run_id),
            entity("service_account", "reset-operator", role="technical_operator"),
            f"restore-before-reset:{time.monotonic_ns()}", dry_run=False,
        )
        result = reset_adapter.execute(request)
        if not result["successful"] or self.fixture.health_mismatches():
            raise ActionContractError("fixture reset failed; preserve run and investigate")
        self._emit("impact.baseline.restored", "Old disposable fixture restored before new run",
                   visibility="facilitator", data=self.fixture.inspect())

    def provision_next_run(self, run_id):
        return self.module.ImpactFixture.provision(self.root, run_id)
