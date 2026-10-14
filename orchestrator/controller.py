"""Deterministic, fail-closed scenario controller for blue-team exercise play."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping

from shared.events import EventBuilder, EventContext, entity

from .scenario import ScenarioDefinition, ScenarioItem


class ControllerError(RuntimeError):
    """Raised when an unsafe or invalid controller operation is requested."""


class RunState(str, Enum):
    """Supported scenario-run lifecycle states."""

    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class ItemStatus(str, Enum):
    """Observable lifecycle states for each MSEL item."""

    PENDING = "pending"
    READY = "ready"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class AutomationResult:
    """A bounded action-handler result retained in the exercise evidence."""

    success: bool
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ItemRuntime:
    """Mutable runtime state separated from the reviewed scenario definition."""

    status: ItemStatus = ItemStatus.PENDING
    delivered_at_seconds: int | None = None
    error: str | None = None


AutomationHandler = Callable[[ScenarioItem, str], AutomationResult]
EventSink = Callable[[Mapping[str, Any]], Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScenarioController:  # pylint: disable=too-many-instance-attributes
    """Run reviewed MSEL items without sleeps, shell commands, or dynamic code."""

    # Runtime dependencies are explicit for deterministic tests and integration.
    # pylint: disable=too-many-arguments
    def __init__(
        self,
        definition: ScenarioDefinition,
        *,
        event_sink: EventSink,
        handlers: Mapping[str, AutomationHandler] | None = None,
        run_id: str | None = None,
        producer_version: str = "1.0.0",
        sequence_factory: Callable[[], int] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.definition = definition
        self.run_id = run_id or str(uuid.uuid4())
        self.event_sink = event_sink
        self.handlers = dict(handlers or {})
        self.producer_version = producer_version
        self.sequence_factory = sequence_factory
        self.clock = clock
        self.state = RunState.READY
        self.elapsed_seconds = 0
        self.time_observers: list[Callable[[int], None]] = []
        self.items = {
            item.item_id: ItemRuntime() for item in self.definition.items
        }
        self.checkpoint_results: dict[str, str] = {}
        self.events = EventBuilder(
            EventContext(
                exercise_id=definition.exercise_id,
                run_id=self.run_id,
                source_kind="controller",
                source_component="scenario-controller",
                producer_version=producer_version,
            ),
            clock=clock,
            sequence_factory=sequence_factory,
        )

    def _definition(self, item_id: str) -> ScenarioItem:
        for item in self.definition.items:
            if item.item_id == item_id:
                return item
        raise ControllerError(f"unknown MSEL item: {item_id}")

    # Event construction intentionally exposes the auditable contract fields.
    # pylint: disable=too-many-arguments
    def _emit(
        self,
        event_type: str,
        action: str,
        message: str,
        *,
        status: str,
        item: ScenarioItem | None = None,
        actor_role: str = "controller",
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.events.build(
            event_type=event_type,
            phase=item.phase if item else "control",
            actor=entity("system", actor_role, role=actor_role),
            action=action,
            target=(
                entity("msel_item", item.item_id, display_name=item.title)
                if item
                else entity("scenario_run", self.run_id)
            ),
            outcome_status=status,
            message=message,
            visibility=item.visibility if item else "facilitator",
            dry_run=False,
            safety_controls=(
                "reviewed-msel",
                "allowlisted-actions",
                "fail-safe-stop",
            ),
            objective_ids=item.objective_ids if item else (),
            checkpoint_id=item.checkpoint_id if item else None,
            data={
                "scenario_id": self.definition.scenario_id,
                "elapsed_seconds": self.elapsed_seconds,
                **dict(data or {}),
            },
        )
        self.event_sink(event)
        return event

    def _require_state(self, *allowed: RunState) -> None:
        if self.state not in allowed:
            expected = ", ".join(state.value for state in allowed)
            raise ControllerError(
                f"operation requires state {expected}; current state is {self.state.value}"
            )

    def prepare(self) -> None:
        """Process pre-exercise items in their reviewed order."""

        self._require_state(RunState.READY)
        items = sorted(
            (
                item
                for item in self.definition.items
                if item.trigger.trigger_type == "pre_exercise"
            ),
            key=lambda item: item.trigger.order,
        )
        for item in items:
            self._make_due(item)

    def start(self) -> None:
        """Start exercise play at elapsed time zero."""

        self._require_state(RunState.READY)
        self.state = RunState.RUNNING
        self._emit(
            "scenario.run.started",
            "scenario.start",
            f"Started {self.definition.name}",
            status="success",
        )
        self.advance_to(0)

    def pause(self) -> None:
        """Pause timed delivery while preserving the complete run state."""

        self._require_state(RunState.RUNNING)
        self.state = RunState.PAUSED
        self._emit(
            "scenario.run.paused",
            "scenario.pause",
            "Scenario timing paused by facilitator",
            status="success",
        )

    def resume(self) -> None:
        """Resume a paused run without advancing its deterministic clock."""

        self._require_state(RunState.PAUSED)
        self.state = RunState.RUNNING
        self._emit(
            "scenario.run.resumed",
            "scenario.resume",
            "Scenario timing resumed by facilitator",
            status="success",
        )

    def advance_to(self, elapsed_seconds: int) -> None:
        """Advance to an absolute exercise time and process due elapsed triggers."""

        self._require_state(RunState.RUNNING)
        if (not isinstance(elapsed_seconds, int) or isinstance(elapsed_seconds, bool)
                or elapsed_seconds < self.elapsed_seconds):
            raise ControllerError("elapsed time must be a non-decreasing integer")
        due = sorted(
            (
                item
                for item in self.definition.items
                if item.trigger.trigger_type == "elapsed"
                and item.trigger.seconds is not None
                and item.trigger.seconds <= elapsed_seconds
                and self.items[item.item_id].status == ItemStatus.PENDING
            ),
            key=lambda item: (item.trigger.seconds or 0, item.trigger.order),
        )
        for item in due:
            self._advance_clock(item.trigger.seconds or 0)
            self._make_due(item)
        self._advance_clock(elapsed_seconds)

    def _advance_clock(self, elapsed_seconds: int) -> None:
        """Notify bounded runtime observers before delivery at each due instant."""

        self.elapsed_seconds = elapsed_seconds
        for observer in self.time_observers:
            observer(elapsed_seconds)

    def _make_due(self, item: ScenarioItem) -> None:
        runtime = self.items[item.item_id]
        if runtime.status != ItemStatus.PENDING:
            return
        if item.delivery == "facilitator" or item.kind == "checkpoint":
            runtime.status = ItemStatus.READY
            self._emit(
                "scenario.item.ready",
                "scenario.ready",
                f"{item.item_id} is ready for facilitator delivery",
                status="pending",
                item=item,
                data={"item_kind": item.kind},
            )
            return
        self._deliver(item, actor_role="controller")

    def _deliver(self, item: ScenarioItem, *, actor_role: str) -> None:
        runtime = self.items[item.item_id]
        if item.action_id:
            handler = self.handlers.get(item.action_id)
            if handler is None:
                self._fail_item(item, f"no allowlisted handler for {item.action_id}")
                return
            try:
                result = handler(item, self.run_id)
            # Handlers are an extension boundary. Convert unknown faults into a
            # visible, redacted failure instead of losing controller state.
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._fail_item(item, f"handler raised {type(exc).__name__}")
                return
            if not isinstance(result, AutomationResult):
                self._fail_item(item, "handler returned an invalid result")
                return
            if not result.success:
                self._fail_item(item, result.message, data=result.data)
                return
            message = result.message
            result_data = dict(result.data)
        else:
            message = item.summary
            result_data = {}

        runtime.status = ItemStatus.DELIVERED
        runtime.delivered_at_seconds = self.elapsed_seconds
        runtime.error = None
        self._emit(
            "scenario.item.delivered",
            item.action_id or "scenario.deliver",
            message,
            status="success",
            item=item,
            actor_role=actor_role,
            data={"item_kind": item.kind, **result_data},
        )
        if item.kind == "end":
            self.state = RunState.COMPLETED

    def _fail_item(
        self,
        item: ScenarioItem,
        reason: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        runtime = self.items[item.item_id]
        runtime.status = ItemStatus.FAILED
        runtime.error = reason
        self._emit(
            "scenario.item.failed",
            item.action_id or "scenario.deliver",
            f"{item.item_id} failed: {reason}",
            status="error",
            item=item,
            data={"item_kind": item.kind, **dict(data or {})},
        )

    def deliver(self, item_id: str) -> None:
        """Deliver a pending or ready item now as an explicit facilitator action."""

        self._require_state(RunState.READY, RunState.RUNNING, RunState.PAUSED)
        item = self._definition(item_id)
        runtime = self.items[item_id]
        if runtime.status not in {ItemStatus.PENDING, ItemStatus.READY}:
            raise ControllerError(
                f"{item_id} cannot be delivered from {runtime.status.value}"
            )
        self._deliver(item, actor_role="facilitator")

    def skip(self, item_id: str, reason: str) -> None:
        """Skip one unprocessed item while preserving the reason in evidence."""

        self._require_state(RunState.READY, RunState.RUNNING, RunState.PAUSED)
        if not reason.strip():
            raise ControllerError("skip reason is required")
        item = self._definition(item_id)
        runtime = self.items[item_id]
        if runtime.status not in {ItemStatus.PENDING, ItemStatus.READY}:
            raise ControllerError(f"{item_id} cannot be skipped from {runtime.status.value}")
        runtime.status = ItemStatus.SKIPPED
        runtime.error = reason.strip()
        self._emit(
            "scenario.item.skipped",
            "scenario.skip",
            f"{item_id} skipped: {reason.strip()}",
            status="skipped",
            item=item,
            actor_role="facilitator",
            data={"item_kind": item.kind, "reason": reason.strip()},
        )

    def resolve_checkpoint(
        self,
        checkpoint_id: str,
        *,
        passed: bool,
        evidence_ids: tuple[str, ...] = (),
        reason: str,
        checks: Mapping[str, bool] | None = None,
    ) -> None:
        """Record an evidence-backed result and run only its matching branch."""

        self._require_state(RunState.RUNNING, RunState.PAUSED)
        item = self._definition(checkpoint_id)
        if item.kind != "checkpoint":
            raise ControllerError(f"{checkpoint_id} is not a checkpoint")
        runtime = self.items[checkpoint_id]
        if runtime.status not in {ItemStatus.PENDING, ItemStatus.READY}:
            raise ControllerError(
                f"{checkpoint_id} cannot be resolved from {runtime.status.value}"
            )
        if not reason.strip():
            raise ControllerError("checkpoint reason is required")
        if checks is not None and (
            not isinstance(checks, Mapping)
            or any(not isinstance(name, str) or not isinstance(value, bool)
                   for name, value in checks.items())
        ):
            raise ControllerError("checkpoint checks must map names to boolean observations")

        result = "pass" if passed else "miss"
        runtime.status = ItemStatus.DELIVERED
        runtime.delivered_at_seconds = self.elapsed_seconds
        self.checkpoint_results[checkpoint_id] = result
        self._emit(
            "scenario.checkpoint.resolved",
            "scenario.checkpoint.evaluate",
            f"{checkpoint_id} result: {result} — {reason.strip()}",
            status="success" if passed else "failure",
            item=item,
            actor_role="facilitator",
            data={
                "result": result,
                "reason": reason.strip(),
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                **({"verifier_checks": dict(checks)} if checks is not None else {}),
            },
        )

        branches = sorted(
            (
                branch
                for branch in self.definition.items
                if branch.trigger.trigger_type == "checkpoint"
                and branch.trigger.checkpoint_id == checkpoint_id
            ),
            key=lambda branch: branch.trigger.order,
        )
        for branch in branches:
            if self.state == RunState.STOPPED:
                break
            if branch.trigger.checkpoint_outcome == result:
                self._make_due(branch)
            else:
                self.skip(branch.item_id, f"opposite {checkpoint_id} branch selected")

    def fail_safe_stop(self, reason: str) -> None:
        """Stop future delivery immediately and record why play was halted."""

        self._require_state(RunState.READY, RunState.RUNNING, RunState.PAUSED)
        if not reason.strip():
            raise ControllerError("stop reason is required")
        self.state = RunState.STOPPED
        self._emit(
            "scenario.run.stopped",
            "scenario.stop",
            f"Fail-safe stop: {reason.strip()}",
            status="cancelled",
            data={"reason": reason.strip()},
        )

    def reset(self, *, new_run_id: str | None = None) -> None:
        """Reset controller memory; infrastructure snapshot reset remains external."""

        self._require_state(RunState.STOPPED, RunState.COMPLETED)
        previous_run_id = self.run_id
        self.run_id = new_run_id or str(uuid.uuid4())
        self.state = RunState.READY
        self.elapsed_seconds = 0
        self.items = {
            item.item_id: ItemRuntime() for item in self.definition.items
        }
        self.checkpoint_results.clear()
        self.events = EventBuilder(
            EventContext(
                exercise_id=self.definition.exercise_id,
                run_id=self.run_id,
                source_kind="controller",
                source_component="scenario-controller",
                producer_version=self.producer_version,
            ),
            clock=self.clock,
            sequence_factory=self.sequence_factory,
        )
        self._emit(
            "scenario.run.reset",
            "scenario.reset",
            "Controller state reset for a new run",
            status="success",
            data={"previous_run_id": previous_run_id},
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-compatible facilitator/evaluator run snapshot."""

        return {
            "scenario_id": self.definition.scenario_id,
            "exercise_id": self.definition.exercise_id,
            "run_id": self.run_id,
            "state": self.state.value,
            "elapsed_seconds": self.elapsed_seconds,
            "checkpoint_results": dict(self.checkpoint_results),
            "items": {
                item_id: {
                    "status": runtime.status.value,
                    "delivered_at_seconds": runtime.delivered_at_seconds,
                    "error": runtime.error,
                }
                for item_id, runtime in self.items.items()
            },
        }
