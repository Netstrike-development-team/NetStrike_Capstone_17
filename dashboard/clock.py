"""Single-process, fail-closed supervision of the existing exercise scheduler."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Callable

from orchestrator.controller import ControllerError, ItemStatus, RunState
from shared.events import EventBuilder, EventContext, entity

if TYPE_CHECKING:
    from .service import PortalService


class ClockSupervisor:
    """All methods share the run lock; inspection never advances or repairs play."""

    # Operational state and broad catches are intentional at this safety boundary:
    # arbitrary synchronous handler/provider/audit failures must latch, not escape.
    # pylint: disable=too-many-instance-attributes,broad-exception-caught

    def __init__(self, service: PortalService, monotonic: Callable[[], float] = time.monotonic):
        self.service = service
        self.monotonic = monotonic
        self.attached = False
        self.managed = False
        self.last_heartbeat: float | None = None
        self.ticks = 0
        self.fault_code: str | None = None
        self.cleanup_complete: bool | None = None
        self.audit_persisted: bool | None = None
        self.stale_after_seconds = 30

    def _age(self) -> float | None:
        if self.last_heartbeat is None:
            return None
        try:
            now = self.monotonic()
            age = now - self.last_heartbeat
            return age if math.isfinite(now) and math.isfinite(age) and age >= 0 else None
        except Exception:  # Clock-provider failure must not expose exception details.
            return None

    def snapshot(self) -> dict:
        """Staff-only operational health, not readiness, grading or live SIEM proof."""
        with self.service.run.state_lock:
            age = self._age()
            if self.fault_code:
                status = "faulted"
            elif not self.managed:
                status = "unmonitored"
            elif not self.attached:
                status = "detached"
            elif age is None:
                status = "invalid_clock"
            elif age > self.stale_after_seconds:
                status = "stale"
            else:
                status = "healthy"
            return {
                "scope": "single_process_application_clock",
                "run_id": self.service.run.run_id,
                "status": status,
                "automatic_delivery_supervised": self.attached,
                "heartbeat_age_seconds": round(age, 3) if age is not None else None,
                "stale_after_seconds": self.stale_after_seconds,
                "successful_ticks": self.ticks,
                "fault_code": self.fault_code,
                "cleanup_complete": self.cleanup_complete,
                "fault_audit_persisted": self.audit_persisted,
                "external_readiness_verified": False,
            }

    def attach(self) -> None:
        """Claim one lifespan driver; reattachment cannot clear a prior run fault."""
        with self.service.run.state_lock:
            if self.attached:
                raise ControllerError("exercise clock already has a driver")
            self.managed = self.attached = True
            try:
                self.last_heartbeat = self.monotonic()
                if self._age() is None:
                    self.fault("invalid_monotonic")
            except Exception:
                self.fault("invalid_monotonic")

    def require_healthy(self) -> None:
        """Gate timed and interactive mutations before any catch-up delivery."""
        with self.service.run.state_lock:
            status = self.snapshot()["status"]
            if (status == "healthy"
                    and self.service.run.controller.state in {RunState.RUNNING, RunState.PAUSED}
                    and any(item.status == ItemStatus.FAILED
                            for item in self.service.run.controller.items.values())):
                self.fault("scheduler_tick_failed")
                status = "faulted"
            if status in {"healthy", "unmonitored"}:
                return
            if not self.fault_code:
                self.fault({"stale": "heartbeat_stale", "invalid_clock": "invalid_monotonic",
                            "detached": "driver_unavailable"}[status])
            raise ControllerError("exercise clock unavailable; preserve evidence and reset safely")

    def tick(self) -> None:
        """Serialize delivery with actions/reset, latch failures, never catch up stale play."""
        with self.service.run.state_lock:
            if self.fault_code or not self.attached:
                return
            try:
                self.require_healthy()
                was_running = self.service.run.controller.state == RunState.RUNNING
                self.service.scheduler.tick()
                if was_running and (
                    self.service.run.controller.state == RunState.STOPPED
                    or any(item.status == ItemStatus.FAILED
                           for item in self.service.run.controller.items.values())
                ):
                    raise ControllerError("scheduled handler failed or stopped delivery")
                self.require_healthy()
                self.last_heartbeat = self.monotonic()
                self.ticks += 1
                self.require_healthy()
            except Exception:  # Keep the driver alive to expose a latched safe failure.
                self.fault("scheduler_tick_failed")

    def fault(self, code: str) -> None:
        """Stop locally even if audit persistence fails; do not erase or rewind evidence."""
        with self.service.run.state_lock:
            if self.fault_code:
                return
            # Codes are server-owned; never publish exception text or caller content.
            self.fault_code = code if code in {
                "heartbeat_stale", "invalid_monotonic", "driver_unavailable",
                "scheduler_tick_failed", "driver_failed",
            } else "driver_failed"
            self.cleanup_complete = True
            actor = entity("system", "exercise-clock", role="technical_operator")
            if self.service.run.controller.state != RunState.COMPLETED:
                try:
                    self.service.run.fail_safe_stop("exercise clock safety stop", operator=actor)
                except Exception:  # All cleanup components are attempted by fail_safe_stop.
                    self.cleanup_complete = False
            self.audit_persisted = False
            try:
                builder = EventBuilder(
                    EventContext(exercise_id=self.service.run.definition.exercise_id,
                                 run_id=self.service.run.run_id, source_kind="controller",
                                 source_component="exercise-clock-supervisor",
                                 producer_version="1.0.0"),
                    sequence_factory=self.service.run.sequencer.next,
                )
                event = builder.build(
                    event_type="exercise.clock.faulted", phase="control", actor=actor,
                    action="exercise.clock.stop",
                    target=entity("scenario_run", self.service.run.run_id),
                    outcome_status="failure", visibility="facilitator", dry_run=False,
                    message="Exercise clock fault latched; preserve evidence before recovery",
                    safety_controls=("fail-closed", "single-process", "no-catch-up"),
                    data={"fault_code": self.fault_code, "cleanup_complete": self.cleanup_complete},
                )
                self.service.store.append_event(event)
                self.audit_persisted = True
            except Exception:  # An unavailable ledger cannot prevent the local safety latch.
                self.audit_persisted = False

    def reset(self) -> None:
        """Only a successfully archived/reset new run may clear the fault latch."""
        with self.service.run.state_lock:
            heartbeat = self.monotonic() if self.attached else None
            if heartbeat is not None and not math.isfinite(heartbeat):
                raise ControllerError("exercise clock reset requires valid monotonic time")
            self.fault_code = self.cleanup_complete = self.audit_persisted = None
            self.ticks = 0
            self.last_heartbeat = heartbeat

    def detach(self) -> None:
        """After the driver drains, stop live play; shutdown is never completion."""
        with self.service.run.state_lock:
            self.attached = False
            if self.service.run.controller.state in {RunState.RUNNING, RunState.PAUSED}:
                try:
                    self.service.run.fail_safe_stop(
                        "exercise clock driver shutdown",
                        operator=entity("system", "exercise-clock", role="technical_operator"),
                    )
                except Exception:
                    self.fault("driver_failed")
