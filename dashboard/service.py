"""Role-neutral portal application service over the identity-slice runtime."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Mapping

from orchestrator.checkpoints import (
    CheckpointEvaluation,
    EvidenceReference,
    IdentityTriageSubmission,
)
from orchestrator.identity_slice import IdentitySliceRun, PARTICIPANT_ACTIONS
from orchestrator.scheduler import ScenarioScheduler
from shared.events import entity

from .auth import PortalPrincipal
from .identity_audit import IdentityAuditRecorder
from .sso import SsoExperience, SsoExperienceConfig
from .store import PortalStore


class PortalService:
    """Expose participant-safe workflows and full facilitator control separately."""

    def __init__(
        self,
        store: PortalStore,
        *,
        run_id: str | None = None,
        scenario_path: Path | str | None = None,
        identity_audit_key: bytes | None = None,
    ) -> None:
        self.store = store
        options: dict[str, Any] = {
            "event_sink": store.append_event,
            "run_id": run_id,
        }
        if scenario_path is not None:
            options["scenario_path"] = scenario_path
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
            "available_actions": sorted(PARTICIPANT_ACTIONS),
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
            "dp2_preview": self.evaluation_dict(self.run.evaluate_dp2()),
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

    def identity_timeline(self) -> list[dict[str, Any]]:
        """Return the current run's queryable synthetic identity timeline."""

        return self.store.identity_audit(
            self.run.definition.exercise_id, self.run.run_id
        )

    def sso_state(self) -> dict[str, Any]:
        """Return the participant-safe current SSO experience state."""

        return self.sso.state()

    def sso_sign_in(self, username: Any, credential: Any) -> dict[str, Any]:
        """Submit one contained synthetic sign-in attempt."""

        return self.sso.sign_in(username, credential)

    def sso_decide_mfa(self, challenge_id: Any, decision: Any) -> dict[str, Any]:
        """Resolve the current synthetic MFA challenge."""

        return self.sso.decide_mfa(challenge_id, decision)

    def sso_review_sessions(self) -> dict[str, Any]:
        """Show configured suspicious sessions after approved sign-in."""

        return self.sso.review_sessions()

    def reset_run(self, *, new_run_id: str | None = None) -> dict[str, Any]:
        """Reset runtime state and remove the prior run's transient audit view."""

        exercise_id = self.run.definition.exercise_id
        prior_run_id = self.run.run_id
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
        }
        if not state["reset"]["sso_baseline_verified"]:
            raise RuntimeError("SSO reset did not reach a clean baseline")
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
