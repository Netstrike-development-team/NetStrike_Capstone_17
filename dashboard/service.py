"""Role-neutral portal application service over the identity-slice runtime."""

from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping

from orchestrator.aar import build_bundle, build_report, validate_judgment, participant_feedback
from orchestrator.checkpoints import (
    CheckpointEvaluation,
    EvidenceReference,
    IdentityTriageSubmission,
)
from orchestrator.identity_slice import IdentitySliceRun, PARTICIPANT_ACTIONS
from orchestrator.cloud import CLOUD_ACTIONS
from orchestrator.scheduler import ScenarioScheduler
from orchestrator.controller import ControllerError
from shared.events import EventBuilder, EventContext, entity

from .auth import PortalPrincipal
from .evidence import project_signal
from .identity_audit import IdentityAuditRecorder
from .sso import SsoExperience, SsoExperienceConfig, SsoExperienceError
from .store import PortalStore
from .readiness import application_readiness
from .clock import ClockSupervisor


def runtime_mutation(method):
    """Use one lock order (run then scheduler/adapter) and guard clock health."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.run.state_lock:
            self.clock.require_healthy()
            return method(self, *args, **kwargs)
    return guarded


def run_snapshot(method):
    """Prevent a snapshot from crossing a concurrent tick or reset boundary."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.run.state_lock:
            return method(self, *args, **kwargs)
    return locked


class PortalService:  # pylint: disable=too-many-public-methods
    """Expose participant-safe workflows and full facilitator control separately."""

    # Deployment inputs stay explicit rather than trusting an arbitrary option map.
    # pylint: disable=too-many-arguments
    def __init__(
        self,
        store: PortalStore,
        *,
        run_id: str | None = None,
        scenario_path: Path | str | None = None,
        profile_path: Path | str | None = None,
        impact_root: Path | str | None = None,
        identity_audit_key: bytes | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        options: dict[str, Any] = {
            "event_sink": store.append_event,
            "run_id": run_id,
        }
        if scenario_path is not None:
            options["scenario_path"] = scenario_path
        if profile_path is not None:
            options["profile_path"] = profile_path
        if impact_root is not None:
            options["impact_root"] = impact_root
        self.run = IdentitySliceRun(**options)
        self.scheduler = ScenarioScheduler(self.run.controller, monotonic=monotonic)
        self.clock = ClockSupervisor(self, monotonic)
        self.identity_audit = IdentityAuditRecorder(
            store,
            audit_key=identity_audit_key or secrets.token_bytes(32),
        )
        sso_configuration = self.run.definition.participant_experience.get("sso")
        self.sso = SsoExperience(
            SsoExperienceConfig.from_mapping(sso_configuration),
            identity_state=lambda: self.run.identity_state,
            audit_sink=lambda payload: self.capture_identity_interaction(
                "simcorp-sso", payload
            ),
        )

    def readiness(self) -> dict[str, Any]:
        """Local pre-play inspection is not VM/Splunk readiness or admission approval."""
        return application_readiness(self)

    def _check_readiness(self, principal: PortalPrincipal, operation: str) -> None:
        if principal.role not in {"facilitator", "technical_operator"}:
            raise ControllerError("Local readiness controls require an exercise-control role")
        report = self.readiness()
        allowed = report[f"ready_to_{operation}"]
        # A corrupt/reused ledger cannot safely accept another audit event.
        if any(check["check_id"] == "event_ledger" and not check["passed"]
               for check in report["checks"]):
            raise ControllerError("Local readiness blocked: event_ledger; preserve evidence and reset safely")
        builder = EventBuilder(
            EventContext(exercise_id=self.run.definition.exercise_id, run_id=self.run.run_id,
                         source_kind="facilitator", source_component="application-readiness",
                         producer_version="1.0.0"),
            sequence_factory=self.run.sequencer.next,
        )
        event = builder.build(
            event_type="exercise.readiness.checked", phase="control",
            actor=entity("facilitator", principal.actor_id, role=principal.role),
            action=f"exercise.readiness.{operation}",
            target=entity("scenario_run", self.run.run_id),
            outcome_status="success" if allowed else "blocked", visibility="facilitator",
            message="Local application readiness checked; external range checks remain required",
            dry_run=False, safety_controls=("local-only", "pre-play-baselines", "fail-closed"),
            data={"operation": operation, "report": report},
        )
        try:
            self.store.append_event(event)  # Persist before any transition.
        except (sqlite3.Error, OSError) as exc:
            raise ControllerError("Local readiness audit unavailable; no transition performed") from exc
        if not allowed:
            blockers = report["blockers"] or ["preparation_incomplete"]
            raise ControllerError("Local readiness blocked: " + ", ".join(blockers))

    @runtime_mutation
    def prepare_run(self, principal: PortalPrincipal) -> dict[str, Any]:
        """Audit and gate preparation; failed setup requires repair/reset, not start."""
        with self.run.state_lock:
            self._check_readiness(principal, "prepare")
            self.run.controller.prepare()
            self._check_readiness(principal, "start")
            return self.facilitator_state()

    @runtime_mutation
    def start_run(self, principal: PortalPrincipal) -> dict[str, Any]:
        """Recheck just before start, preparing first for existing Start-only clients."""
        with self.run.state_lock:
            if not self.readiness()["preparation_complete"]:
                self.prepare_run(principal)
            self._check_readiness(principal, "start")
            self.scheduler.start()
            return self.facilitator_state()

    @run_snapshot
    def participant_state(self) -> dict[str, Any]:
        """Return only participant-visible injects and non-sensitive run metadata."""

        events = self.store.events(
            self.run.definition.exercise_id,
            self.run.run_id,
            visibilities=frozenset({"participant"}),
        )
        injects = [
            {
                "event_id": event["event_id"],
                "timestamp": event["timestamp"],
                "phase": event["phase"],
                "message": event["message"],
                "msel_id": (event.get("target") or {}).get("id"),
            }
            for event in events
            if event["event_type"] == "scenario.item.delivered"
            and event["data"].get("item_kind") == "inject"
        ]
        return {
            "exercise_id": self.run.definition.exercise_id,
            "run_id": self.run.run_id,
            "state": self.run.controller.state.value,
            "elapsed_seconds": self.run.controller.elapsed_seconds,
            "injects": injects,
            "available_actions": sorted(PARTICIPANT_ACTIONS | (
                CLOUD_ACTIONS if self.run.cloud_enabled else frozenset()
            )),
            "cloud_enabled": self.run.cloud_enabled,
            "impact_enabled": self.run.impact_enabled,
        }

    def participant_evidence(
        self, principal: PortalPrincipal, *, after_sequence: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        """Current-run facts in ingestion order, scoped to the authenticated actor."""
        if after_sequence < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid evidence page boundary")
        with self.run.state_lock:
            signals = [
                signal for event in self.store.events(
                    self.run.definition.exercise_id, self.run.run_id,
                ) if event["sequence"] > after_sequence
                and (signal := project_signal(event, principal.actor_id)) is not None
            ]
            page = signals[:limit]
            return {
                "exercise_id": self.run.definition.exercise_id, "run_id": self.run.run_id,
                "state": self.run.controller.state.value,
                "elapsed_seconds": self.run.controller.elapsed_seconds,
                "environment": "local_synthetic_evidence_not_splunk",
                "ordering": "ingestion_sequence_not_occurrence_time",
                "signals": page, "has_more": len(signals) > limit,
                "next_sequence": page[-1]["sequence"] if page else after_sequence,
            }

    @run_snapshot
    def facilitator_state(self) -> dict[str, Any]:
        """Return controller state, all events, submissions, and verifier state."""

        snapshot = self.run.controller.snapshot()
        return {
            "controller": snapshot,
            "clock": self.clock.snapshot(),
            "msel": [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "kind": item.kind,
                    "phase": item.phase,
                    "delivery": item.delivery,
                    "trigger": item.trigger.trigger_type,
                    "trigger_seconds": item.trigger.seconds,
                    **snapshot["items"][item.item_id],
                }
                for item in self.run.definition.items
            ],
            "events": self.store.events(
                self.run.definition.exercise_id, self.run.run_id
            ),
            "submissions": self.store.submissions(self.run.run_id),
            "identity_audit": self.identity_timeline(),
            "sso": self.sso.state(),
            "scheduled_mfa": self.run.mfa.snapshot(),
            "profile_initialization": self.run.profiles.summary(),
            "dp2_preview": self.evaluation_dict(self.run.evaluate_dp2()),
            "cloud": {
                "enabled": self.run.cloud_enabled,
                "dp3_preview": self.evaluation_dict(self.run.cloud.evaluate()),
                "state": self.run.cloud.view(),
            },
            "impact": self.run.impact.staff_state() if self.run.impact else {"enabled": False},
        }

    @runtime_mutation
    def capture_identity_interaction(
        self,
        source_service: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record a safe identity interaction for the authoritative current run."""

        with self.run.state_lock:
            return self.identity_audit.record(
                exercise_id=self.run.definition.exercise_id,
                run_id=self.run.run_id,
                source_service=source_service,
                sequence_factory=self.run.sequencer.next,
                payload=payload,
            )

    def participant_directory(self) -> list[dict[str, Any]]:
        """Read-only reviewed directory, without target bindings or attack rankings."""

        return self.run.profiles.directory()

    def aar_bundle(self) -> dict[str, Any]:
        """Snapshot everything needed for offline staff review, under one lock."""
        with self.run.state_lock:
            return build_bundle(
                exercise_id=self.run.definition.exercise_id,
                run_id=self.run.run_id,
                scenario_id=self.run.definition.scenario_id,
                run_state=self.run.controller.state.value,
                checkpoint_ids=[
                    item.item_id
                    for item in self.run.definition.items
                    if item.kind == "checkpoint"
                ],
                events=self.store.events(
                    self.run.definition.exercise_id, self.run.run_id
                ),
                submissions=self.store.submissions(self.run.run_id),
            )

    def aar_report(self) -> dict[str, Any]:
        """Machine observations do not replace attributable human judgments."""
        return build_report(self.aar_bundle())

    def capture_review_archive(
        self, principal: PortalPrincipal, *, run_id: str, expected_bundle_sha256: str,
    ) -> dict[str, Any]:
        """Guard against stale run/hash inputs and replay exact captures without effects."""
        if principal.role not in {"facilitator", "evaluator"}:
            raise ControllerError("review archive capture requires a review role")
        with self.run.state_lock:
            if run_id != self.run.run_id:
                raise ValueError("run changed; refresh before archiving")
            if self.run.controller.state.value not in {"stopped", "completed"}:
                raise ValueError("review archive requires stopped or completed play")
            existing = self.store.review_archive_by_hash(
                self.run.definition.exercise_id, run_id, expected_bundle_sha256,
            )
            if existing:
                return {"status": "already_captured", "metadata": existing["metadata"]}
            bundle = self.aar_bundle()
            if expected_bundle_sha256 != bundle["content_sha256"]:
                raise ValueError("review changed; refresh before archiving")
            return {"status": "captured", "metadata": self._capture_review(
                bundle, entity("facilitator", principal.actor_id, role=principal.role), "staff_capture",
            )}

    def _capture_review(self, bundle: dict, actor: dict, reason: str) -> dict:
        """Atomically freeze a terminal snapshot plus its audit, before runtime reset."""
        identifier = str(uuid.uuid4())
        last_sequence = bundle["events"][-1]["sequence"] if bundle["events"] else 0
        if self.run.sequencer.sequence != last_sequence:
            raise ValueError("review archive requires consistent live ledger sequencing")
        builder = EventBuilder(
            EventContext(exercise_id=self.run.definition.exercise_id, run_id=self.run.run_id,
                         source_kind="facilitator", source_component="review-archive",
                         producer_version="1.0.0"),
            sequence_factory=self.run.sequencer.next,
        )
        try:
            event = builder.build(
                event_type="evaluation.archive.created", phase="post_exercise",
                actor=actor, action="evaluation.archive.capture", target=entity("review_archive", identifier),
                outcome_status="success", visibility="evaluator",
                message="Terminal review snapshot captured; later reset/cleanup events are outside its boundary",
                dry_run=False, safety_controls=("staff-only", "immutable-snapshot", "no-branch-mutation"),
                data={"archive_id": identifier, "bundle_sha256": bundle["content_sha256"],
                      "last_sequence": last_sequence, "capture_reason": reason},
            )
            return self.store.append_review_archive(bundle, event)
        except (ValueError, sqlite3.Error, OSError) as exc:
            # A failed transaction can cancel its reservation only after confirming
            # the old ledger is unchanged. Never rewind over persisted evidence.
            try:
                current = self.store.events(self.run.definition.exercise_id, self.run.run_id)
                if current == bundle["events"]:
                    self.run.sequencer.reset(last_sequence)
            except (ValueError, sqlite3.Error, OSError):
                pass  # Unreadable persistence remains fail-closed until repaired.
            raise ControllerError("review archive capture failed; no reset performed") from exc

    def review_archives(self, *, after_sequence: int = 0, limit: int = 50) -> dict:
        return self.store.review_archives(
            self.run.definition.exercise_id, after_sequence=after_sequence, limit=limit,
        )

    def review_archive(self, identifier: str) -> dict | None:
        return self.store.review_archive(self.run.definition.exercise_id, identifier)

    def judge_objective(
        self, principal: PortalPrincipal, payload: dict, *, run_id: str
    ) -> dict[str, Any]:
        """Append a review after play; never overwrite events or alter branches."""
        with self.run.state_lock:
            if run_id != self.run.run_id:
                raise ValueError("run changed; refresh before reviewing")
            if self.run.controller.state.value not in {"stopped", "completed"}:
                raise ValueError("objective review requires stopped or completed play")
            bundle = self.aar_bundle()
            report = build_report(bundle)
            item = next(
                (
                    item
                    for item in report["objectives"]
                    if item["objective_id"] == payload["objective_id"]
                ),
                None,
            )
            if item is None:
                raise ValueError("unknown learning objective")
            references = {event["event_id"] for event in bundle["events"]}
            references.update(
                f"submission:{item['submission_id']}" for item in bundle["submissions"]
            )
            validate_judgment(
                payload,
                references=references,
                previous=item["judgment"],
                observation=item["observation"],
            )
            builder = EventBuilder(
                EventContext(
                    exercise_id=self.run.definition.exercise_id,
                    run_id=self.run.run_id,
                    source_kind="facilitator",
                    source_component="objective-evaluator",
                    producer_version="1.0.0",
                ),
                sequence_factory=self.run.sequencer.next,
            )
            event = builder.build(
                event_type="evaluation.objective.judged",
                phase="post_exercise",
                actor=entity("facilitator", principal.actor_id, role=principal.role),
                action="evaluation.objective.judge",
                target=entity("objective", payload["objective_id"]),
                outcome_status="success",
                message="Attributable objective review recorded",
                visibility="evaluator",
                objective_ids=(payload["objective_id"],),
                data={
                    **payload,
                    "revision": payload["expected_revision"] + 1,
                    "supersedes_event_id": (
                        item["judgment"]["event_id"] if item["judgment"] else None
                    ),
                },
                safety_controls=("staff-only", "append-only", "no-branch-mutation"),
            )
            self.store.append_event(event)
            return {
                "event_id": event["event_id"],
                "revision": event["data"]["revision"],
                "run_id": self.run.run_id,
                "status": "recorded",
            }

    def participant_feedback(self) -> dict[str, Any]:
        """Participant feedback contains no evaluator free text or answer key."""
        return participant_feedback(self.aar_report())

    def submit_timeline(
        self, principal: PortalPrincipal, *, run_id: str, entries: list
    ) -> dict:
        """Retain learner fact/inference statements without automatically grading prose."""
        with self.run.state_lock:
            if run_id != self.run.run_id:
                raise ValueError("run changed; refresh before submitting")
            controller = self.run.controller
            dp2 = next(
                item for item in self.run.definition.items if item.item_id == "DP2"
            )
            if (
                controller.state.value not in {"running", "paused"}
                or "DP2" in controller.checkpoint_results
                or controller.elapsed_seconds > dp2.trigger.seconds
            ):
                raise ValueError(
                    "timeline must be submitted during play before the containment checkpoint"
                )
            events = self.store.events(self.run.definition.exercise_id, self.run.run_id)
            visible_ids = {
                event["event_id"]
                for event in events
                if project_signal(event, principal.actor_id) is not None
            }
            references = [entry["event_id"] for entry in entries]
            if (
                len(references) != len(set(references))
                or not set(references) <= visible_ids
            ):
                raise ValueError(
                    "timeline requires distinct current-run participant-visible event IDs"
                )
            submission_id = self.store.save_submission(
                exercise_id=self.run.definition.exercise_id,
                run_id=self.run.run_id,
                actor_id=principal.actor_id,
                submission_type="intrusion_timeline",
                payload={
                    "entries": entries,
                    "elapsed_seconds": controller.elapsed_seconds,
                },
                result={"status": "submitted", "quality_requires_evaluator": True},
            )
            return {
                "submission_id": submission_id,
                "run_id": self.run.run_id,
                "status": "submitted",
            }

    def cloud_view(self) -> dict[str, Any]:
        """Expose synthetic objects, current policy and actual audit events only."""
        with self.run.state_lock:
            if not self.run.cloud_enabled:
                raise ValueError("selected scenario has no cloud stage")
            return self.run.cloud.view()

    @runtime_mutation
    def submit_cloud_assessment(self, principal: PortalPrincipal, **payload) -> dict[str, Any]:
        """Retain the learner's assessment without returning hidden grading logic."""
        with self.run.state_lock:
            if not self.run.cloud_enabled:
                raise ValueError("selected scenario has no cloud stage")
            self.run.cloud.submit_assessment(**payload)
            submission_id = self.store.save_submission(
                exercise_id=self.run.definition.exercise_id, run_id=self.run.run_id,
                actor_id=principal.actor_id, submission_type="DP3",
                payload=self.run.cloud.assessment, result={"status": "submitted"},
            )
            return {
                "submission_id": submission_id, "status": "submitted",
                "run_id": self.run.run_id,
            }

    @runtime_mutation
    def resolve_cloud(self):
        """Resolve cloud grading and its branch under the shared mutation lock."""
        with self.run.state_lock:
            return self.run.cloud.resolve()

    def require_impact(self):
        if not self.run.impact:
            raise ValueError("selected scenario has no impact/recovery stage")
        return self.run.impact

    def impact_view(self):
        return self.require_impact().view()

    @runtime_mutation
    def recover_fixture(self, principal, **payload):
        return self.require_impact().recover(
            actor=entity("participant", principal.actor_id, role=principal.role), **payload,
        )

    @runtime_mutation
    def resolve_impact(self):
        return self.require_impact().resolve()

    def rollback_impact(self, principal):
        return self.require_impact().rollback(
            entity("facilitator", principal.actor_id, role=principal.role),
        )

    def submit_recovery_brief(self, principal, payload):
        with self.run.state_lock:
            self.require_impact().submit_brief(payload)
            submission_id = self.store.save_submission(
                exercise_id=self.run.definition.exercise_id, run_id=self.run.run_id,
                actor_id=principal.actor_id, submission_type="recovery_brief",
                payload=payload, result={"status": "submitted"},
            )
            return {
                "submission_id": submission_id, "status": "submitted",
                "run_id": self.run.run_id,
            }

    def identity_timeline(self) -> list[dict[str, Any]]:
        """Return the current run's queryable synthetic identity timeline."""

        return self.store.identity_audit(
            self.run.definition.exercise_id, self.run.run_id
        )

    def sso_state(self) -> dict[str, Any]:
        """Return the participant-safe current SSO experience state."""

        state = self.sso.state()
        scheduled = self.run.mfa.snapshot()
        state["exercise_state"] = scheduled["state"]
        state["scheduled_result"] = (
            scheduled["history"][-1] if scheduled["history"] else None
        )
        if scheduled["pending"]:
            state.update(view="mfa", challenge=scheduled["pending"],
                         display_name=self.sso.config.display_name,
                         message="Unexpected exercise sign-in request. "
                                 "Approve only if you initiated it.")
        return state

    @runtime_mutation
    def sso_sign_in(self, username: Any, credential: Any) -> dict[str, Any]:
        """Submit one contained synthetic sign-in attempt."""

        with self.run.state_lock:
            self._require_sso_active()
            if self.run.mfa.snapshot()["pending"]:
                return self.sso_state()
            self.sso.sign_in(username, credential)
            self.run.mfa.advance(self.run.controller.elapsed_seconds)
            return self.sso_state()

    @runtime_mutation
    def sso_decide_mfa(self, challenge_id: Any, decision: Any) -> dict[str, Any]:
        """Resolve the current synthetic MFA challenge."""

        with self.run.state_lock:
            self._require_sso_active()
            if self.run.mfa.snapshot()["pending"]:
                raise SsoExperienceError("scheduled challenge requires authenticated MFA decision")
            self.sso.decide_mfa(challenge_id, decision)
            return self.sso_state()

    def _require_sso_active(self) -> None:
        if self.run.controller.state.value in {"paused", "stopped", "completed"}:
            raise SsoExperienceError(
                "SSO changes are unavailable while exercise is paused or stopped"
            )

    @runtime_mutation
    def decide_scheduled_mfa(
        self, principal: PortalPrincipal, challenge_id: Any, decision: Any,
    ) -> dict[str, Any]:
        """Bind the human decision to the authenticated staff/user principal."""

        self.run.mfa.decide(
            challenge_id, decision,
            entity("facilitator" if principal.role == "facilitator" else "participant",
                   principal.actor_id, role=principal.role),
        )
        return self.sso_state()

    @runtime_mutation
    def sso_review_sessions(self) -> dict[str, Any]:
        """Show configured suspicious sessions after approved sign-in."""

        with self.run.state_lock:
            self._require_sso_active()
            return self.sso.review_sessions()

    def reset_run(self, *, new_run_id: str | None = None,
                  principal: PortalPrincipal | None = None) -> dict[str, Any]:
        """Reset runtime state and remove the prior run's transient audit view."""

        with self.run.state_lock:
            if principal and principal.role not in {"facilitator", "technical_operator"}:
                raise ControllerError("reset requires an exercise-control role")
            return self._reset_run(new_run_id=new_run_id, principal=principal)

    def _reset_run(self, *, new_run_id: str | None = None,
                   principal: PortalPrincipal | None = None) -> dict[str, Any]:
        """Hold the same mutation boundary through SSO and audit cleanup."""

        exercise_id = self.run.definition.exercise_id
        prior_run_id = self.run.run_id
        if self.run.controller.state.value not in {"stopped", "completed"}:
            raise ControllerError("run must be stopped or completed before reset")
        new_run_id = new_run_id or str(uuid.uuid4())
        if new_run_id and (
            new_run_id == prior_run_id or self.store.events(exercise_id, new_run_id)
        ):
            raise SsoExperienceError("reset requires a new, unused run id")
        if self.run.impact:
            self.run.impact.validate_next_run(new_run_id)
        actor = (entity("facilitator", principal.actor_id, role=principal.role) if principal
                 else entity("system", "application-reset", role="system"))
        archive = self._capture_review(self.aar_bundle(), actor, "application_reset")
        self.run.reset(new_run_id=new_run_id)
        self.scheduler.reset()
        self.sso.reset()
        deleted = self.store.delete_identity_audit(exercise_id, prior_run_id)
        if self.store.identity_audit(exercise_id, prior_run_id):
            raise RuntimeError("identity audit cleanup did not reach a clean baseline")
        state = self.facilitator_state()
        state["reset"] = {
            "prior_run_id": prior_run_id,
            "review_archive_id": archive["archive_id"],
            "identity_audit_records_deleted": deleted,
            "identity_audit_baseline_verified": True,
            "sso_baseline_verified": not self.sso.baseline_mismatches(),
            "scheduled_mfa_baseline_verified": not self.run.mfa.snapshot()["history"],
            "profile_baseline_verified": not self.run.identity_state.readiness_mismatches(),
        }
        if self.run.cloud_enabled:
            state["reset"]["cloud_baseline_verified"] = (
                not self.run.cloud.state.readiness_mismatches()
            )
            if (not state["reset"]["cloud_baseline_verified"]
                    or self.run.cloud.audit or self.run.cloud.assessment):
                raise RuntimeError("cloud reset did not reach a clean baseline")
        if self.run.impact:
            state["reset"]["impact_baseline_verified"] = (
                self.run.impact.fixture.inspect()["baseline_verified"]
                and not self.run.impact.audit and self.run.impact.brief is None
            )
            if not state["reset"]["impact_baseline_verified"]:
                raise RuntimeError("impact reset did not reach a clean baseline")
        if not all(state["reset"][key] for key in (
            "sso_baseline_verified", "profile_baseline_verified", "scheduled_mfa_baseline_verified",
        )):
            raise RuntimeError("SSO/profile/MFA reset did not reach a clean baseline")
        self.clock.reset()
        state["clock"] = self.clock.snapshot()
        return state

    @runtime_mutation
    def control_run(self, operation: str, *args) -> dict[str, Any]:
        """Staff routes use the same guarded mutation boundary as participant actions."""
        controls = {
            "pause": self.scheduler.pause,
            "resume": self.scheduler.resume,
            "advance": self.scheduler.advance_to,
            "deliver": self.run.controller.deliver,
            "skip": self.run.controller.skip,
        }
        if operation not in controls:
            raise ControllerError("unsupported exercise control")
        controls[operation](*args)
        return self.facilitator_state()

    @runtime_mutation
    def resolve_dp2(self):
        """Serialize checkpoint resolution with delivery and reset."""
        return self.run.resolve_dp2()

    @run_snapshot
    def stop_run(self, reason: str, principal: PortalPrincipal) -> dict[str, Any]:
        """Emergency stop remains available during a latched clock fault."""
        if principal.role not in {"facilitator", "technical_operator"}:
            raise ControllerError("stop requires an exercise-control role")
        self.run.fail_safe_stop(reason, operator=entity("facilitator", principal.actor_id,
                                                       role=principal.role))
        return self.facilitator_state()

    # Action fields remain explicit so the service cannot trust client actor data.
    # pylint: disable=too-many-arguments
    @runtime_mutation
    def submit_action(
        self,
        principal: PortalPrincipal,
        *,
        action_id: str,
        target_type: str,
        target_id: str,
        idempotency_key: str,
        parameters: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Submit one role-bound action without trusting actor fields from JSON."""

        return self.run.submit_action(
            actor=entity(
                "participant", principal.actor_id, role=principal.role
            ),
            action_id=action_id,
            target=entity(target_type, target_id),
            idempotency_key=idempotency_key,
            parameters=parameters,
            dry_run=dry_run,
        )

    @runtime_mutation
    def submit_dp1(
        self,
        principal: PortalPrincipal,
        *,
        affected_identity: str,
        classification: str,
        evidence: tuple[tuple[str, str], ...],
    ) -> dict[str, Any]:
        """Evaluate, persist, and return one structured DP1 submission."""

        submission = IdentityTriageSubmission(
            affected_identity=affected_identity,
            classification=classification,
            evidence=tuple(
                EvidenceReference(reference_id, source)
                for reference_id, source in evidence
            ),
        )
        result = self.run.submit_dp1(submission)
        result_data = self.evaluation_dict(result)
        submission_id = self.store.save_submission(
            exercise_id=self.run.definition.exercise_id,
            run_id=self.run.run_id,
            actor_id=principal.actor_id,
            submission_type="DP1",
            payload={
                "affected_identity": affected_identity,
                "classification": classification,
                "evidence": [
                    {"reference_id": reference, "source": source}
                    for reference, source in evidence
                ],
            },
            result=result_data,
        )
        return {"submission_id": submission_id, **result_data}

    @staticmethod
    def evaluation_dict(result: CheckpointEvaluation) -> dict[str, Any]:
        return {
            "passed": result.passed,
            "reason": result.reason,
            "evidence_ids": list(result.evidence_ids),
            "checks": dict(result.checks),
        }
