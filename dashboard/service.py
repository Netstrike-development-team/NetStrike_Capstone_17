"""Role-neutral portal application service over the identity-slice runtime."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Mapping

from orchestrator.aar import build_bundle, build_report, validate_judgment, participant_feedback
from orchestrator.checkpoints import (
    CheckpointEvaluation,
    EvidenceReference,
    IdentityTriageSubmission,
)
from orchestrator.identity_slice import IdentitySliceRun, PARTICIPANT_ACTIONS
from orchestrator.cloud import CLOUD_ACTIONS
from orchestrator.scheduler import ScenarioScheduler
from shared.events import EventBuilder, EventContext, entity

from .auth import PortalPrincipal
from .evidence import project_signal
from .identity_audit import IdentityAuditRecorder
from .sso import SsoExperience, SsoExperienceConfig, SsoExperienceError
from .store import PortalStore


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
        self.scheduler = ScenarioScheduler(self.run.controller)
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

    def facilitator_state(self) -> dict[str, Any]:
        """Return controller state, all events, submissions, and verifier state."""

        snapshot = self.run.controller.snapshot()
        return {
            "controller": snapshot,
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

    def capture_identity_interaction(
        self,
        source_service: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record a safe identity interaction for the authoritative current run."""

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

    def recover_fixture(self, principal, **payload):
        return self.require_impact().recover(
            actor=entity("participant", principal.actor_id, role=principal.role), **payload,
        )

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

    def sso_sign_in(self, username: Any, credential: Any) -> dict[str, Any]:
        """Submit one contained synthetic sign-in attempt."""

        with self.run.state_lock:
            self._require_sso_active()
            if self.run.mfa.snapshot()["pending"]:
                return self.sso_state()
            self.sso.sign_in(username, credential)
            self.run.mfa.advance(self.run.controller.elapsed_seconds)
            return self.sso_state()

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

    def sso_review_sessions(self) -> dict[str, Any]:
        """Show configured suspicious sessions after approved sign-in."""

        self._require_sso_active()
        return self.sso.review_sessions()

    def reset_run(self, *, new_run_id: str | None = None) -> dict[str, Any]:
        """Reset runtime state and remove the prior run's transient audit view."""

        exercise_id = self.run.definition.exercise_id
        prior_run_id = self.run.run_id
        if new_run_id and (
            new_run_id == prior_run_id or self.store.events(exercise_id, new_run_id)
        ):
            raise SsoExperienceError("reset requires a new, unused run id")
        self.run.reset(new_run_id=new_run_id)
        self.scheduler.reset()
        self.sso.reset()
        deleted = self.store.delete_identity_audit(exercise_id, prior_run_id)
        if self.store.identity_audit(exercise_id, prior_run_id):
            raise RuntimeError("identity audit cleanup did not reach a clean baseline")
        state = self.facilitator_state()
        state["reset"] = {
            "prior_run_id": prior_run_id,
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
        return state

    # Action fields remain explicit so the service cannot trust client actor data.
    # pylint: disable=too-many-arguments
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
