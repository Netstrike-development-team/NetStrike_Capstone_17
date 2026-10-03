"""End-to-end identity vertical-slice runtime built from safe project components."""

from __future__ import annotations

import importlib
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.actions import (
    ActionContractError,
    ActionDefinition,
    ActionEffect,
    ActionExecutionError,
    ActionRegistry,
    ExecutionControl,
    SafeActionAdapter,
    make_action_request,
)
from shared.events import EventBuilder, EventContext, EventSequencer, entity
from shared.profiles import ProfileCatalog, ProfileInitializationError

from .checkpoints import (
    CheckpointEvaluation,
    IdentityTriageSubmission,
    evaluate_identity_endpoint_containment,
    evaluate_identity_triage,
)
from .controller import AutomationResult, ControllerError, RunState, ScenarioController
from .cloud import CLOUD_ACTIONS, CloudStage
from .impact import ImpactStage
from .mfa import ScheduledMfa
from .scenario import ScenarioItem, load_scenario


DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parent / "scenarios" / "identity-slice.v1.json"
)
DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "fixtures" / "identity-profiles.v1.json"
IDENTITY_ACTIONS = frozenset(
    {
        "identity.session.revoke",
        "identity.factor.remove",
        "identity.account.disable",
        "identity.credential.reset",
    }
)
ENDPOINT_ACTIONS = frozenset(
    {
        "endpoint.host.isolate",
        "evidence.artifact.preserve",
        "ad.account.disable",
        "ad.persistence.remove",
        "endpoint.process.stop",
    }
)
PARTICIPANT_ACTIONS = frozenset(
    {
        "identity.session.revoke",
        "identity.factor.remove",
        "identity.account.disable",
        "identity.credential.reset",
        "endpoint.host.isolate",
        "evidence.artifact.preserve",
        "ad.account.disable",
        "ad.persistence.remove",
        "endpoint.process.stop",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _no_parameters(parameters: Mapping[str, Any]) -> None:
    if parameters:
        raise ValueError("scenario automation actions accept no parameters")


@dataclass
# State fields mirror reviewed transitions and must be independently inspectable.
# pylint: disable=too-many-instance-attributes
class IdentitySliceSimulationState:
    """Run-scoped state for allowlisted attacker-side simulation steps."""

    endpoint_state: Any
    baseline_loaded: bool = False
    history_staged: bool = False
    session_replays: int = 0
    discovery_runs: int = 0
    persistence_attempted: bool = False
    blocked_post_containment_auth: bool = False
    adverse_persistence_created: bool = False
    _rollbacks: dict[str, dict[str, Any]] = field(default_factory=dict)
    _rollback_sequence: int = 0

    def _snapshot(self) -> dict[str, Any]:
        return {
            "baseline_loaded": self.baseline_loaded,
            "history_staged": self.history_staged,
            "session_replays": self.session_replays,
            "discovery_runs": self.discovery_runs,
            "persistence_attempted": self.persistence_attempted,
            "blocked_post_containment_auth": self.blocked_post_containment_auth,
            "adverse_persistence_created": self.adverse_persistence_created,
            "endpoint_accounts": deepcopy(self.endpoint_state.accounts),
        }

    def _capture(self) -> str:
        self._rollback_sequence += 1
        token = f"identity-slice-rb-{self._rollback_sequence}"
        self._rollbacks[token] = self._snapshot()
        return token

    # One registry owns every reviewed transition for straightforward audit.
    # pylint: disable=too-many-branches
    def apply(
        self,
        action_id: str,
        control: ExecutionControl,
        containment_check: Callable[[], CheckpointEvaluation],
    ) -> ActionEffect:
        """Apply exactly one reviewed simulation transition."""

        control.checkpoint()
        token = self._capture()
        if action_id == "scenario.baseline.load":
            self.baseline_loaded = True
            effects = ("validated and loaded identity-slice baseline",)
        elif action_id == "identity.history.stage":
            if not self.baseline_loaded:
                raise ActionExecutionError(
                    "baseline_not_loaded", "Baseline must be loaded before history"
                )
            self.history_staged = True
            effects = ("staged six correlated pre-exercise evidence events",)
        elif action_id == "identity.session.replay":
            if not self.history_staged:
                raise ActionExecutionError(
                    "history_not_staged", "Identity history must be staged first"
                )
            self.session_replays += 1
            effects = ("replayed synthetic compromised-session access",)
        elif action_id == "endpoint.discovery.run":
            if self.session_replays < 1:
                raise ActionExecutionError(
                    "session_not_replayed", "Compromised access evidence is missing"
                )
            self.discovery_runs += 1
            effects = ("recorded allowlisted endpoint and directory discovery",)
        elif action_id == "identity.persistence.attempt":
            if self.discovery_runs < 1:
                raise ActionExecutionError(
                    "discovery_not_run", "Discovery must precede persistence attempt"
                )
            self.persistence_attempted = True
            effects = ("recorded designated persistence attempt",)
        elif action_id == "identity.containment.verify":
            result = containment_check()
            if not result.passed:
                raise ActionExecutionError("containment_mismatch", result.reason)
            self.blocked_post_containment_auth = True
            effects = ("recorded blocked post-containment authentication",)
        elif action_id == "identity.persistence.escalate":
            account = self.endpoint_state.accounts["svc-print-sync"]
            account.update(
                {
                    "exists": True,
                    "enabled": True,
                    "groups": ["SimCorp-Server-Operators"],
                }
            )
            self.adverse_persistence_created = True
            effects = ("created designated adverse-branch persistence state",)
        else:
            raise ActionExecutionError("unregistered_transition", "Unknown transition")
        return ActionEffect(
            effects=effects,
            rollback_token=token,
            metadata=self._snapshot(),
        )

    def rollback(
        self, token: str, control: ExecutionControl
    ) -> tuple[str, ...]:
        """Restore the captured simulation and endpoint account state."""

        control.checkpoint()
        try:
            snapshot = self._rollbacks.pop(token)
        except KeyError as exc:
            raise ActionExecutionError(
                "invalid_rollback", "Unknown or already-used rollback token"
            ) from exc
        self.baseline_loaded = snapshot["baseline_loaded"]
        self.history_staged = snapshot["history_staged"]
        self.session_replays = snapshot["session_replays"]
        self.discovery_runs = snapshot["discovery_runs"]
        self.persistence_attempted = snapshot["persistence_attempted"]
        self.blocked_post_containment_auth = snapshot[
            "blocked_post_containment_auth"
        ]
        self.adverse_persistence_created = snapshot[
            "adverse_persistence_created"
        ]
        self.endpoint_state.accounts = snapshot["endpoint_accounts"]
        return ("restored pre-transition identity-slice state",)


class IdentitySliceAutomation:  # pylint: disable=too-many-instance-attributes
    """Bridge controller MSEL actions to audited, allowlisted simulation steps."""

    _ACTION_ITEMS = {
        "scenario.baseline.load": "PRE-01",
        "identity.history.stage": "PRE-02",
        "identity.session.replay": "ACT-01",
        "endpoint.discovery.run": "ACT-02",
        "identity.persistence.attempt": "ACT-03",
        "identity.containment.verify": "ACT-04A",
        "identity.persistence.escalate": "ACT-04B",
    }

    # Collaborators are explicit because they form the safety boundary.
    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        exercise_id: str,
        run_id: str,
        endpoint_state: Any,
        run_state: Callable[[str, str], str],
        containment_check: Callable[[], CheckpointEvaluation],
        event_sink: Callable[[Mapping[str, Any]], Any],
        sequence_factory: Callable[[], int],
        clock: Callable[[], datetime] = _utc_now,
        profile_summary: Mapping[str, Any],
    ) -> None:
        self.exercise_id = exercise_id
        self.run_id = run_id
        self.event_sink = event_sink
        self.clock = clock
        self.profile_summary = deepcopy(dict(profile_summary))
        self.profile_context = self.profile_summary["bindings"]
        self.containment_check = containment_check
        self.state = IdentitySliceSimulationState(endpoint_state)
        self._emitted: set[str] = set()

        registry = ActionRegistry()
        for action_id, item_id in self._ACTION_ITEMS.items():
            allowed_states = (
                frozenset({"ready"})
                if item_id.startswith("PRE-")
                else frozenset({"running", "paused"})
                if item_id.startswith("ACT-04")
                else frozenset({"running"})
            )

            def execute(_parameters, _target, control, current=action_id):
                return self.state.apply(current, control, self.containment_check)

            registry.register(
                ActionDefinition(
                    action_id=action_id,
                    phase="setup" if item_id.startswith("PRE-") else "identity",
                    allowed_roles=frozenset({"scenario_engine", "facilitator"}),
                    allowed_targets=frozenset({f"msel_item:{item_id}"}),
                    allowed_run_states=allowed_states,
                    max_timeout_seconds=20,
                    expected_effects=(action_id,),
                    rollback_method="restore captured simulation state",
                    handler=execute,
                    rollback_handler=self.state.rollback,
                    parameter_validator=_no_parameters,
                )
            )
        self.adapter = SafeActionAdapter(
            context=EventContext(
                exercise_id=exercise_id,
                run_id=run_id,
                source_kind="action_adapter",
                source_component="identity-slice-automation",
                producer_version="1.0.0",
            ),
            registry=registry,
            run_state=run_state,
            event_sink=event_sink,
            clock=clock,
            sequence_factory=sequence_factory,
        )
        self.builders = {
            name: EventBuilder(
                EventContext(
                    exercise_id=exercise_id,
                    run_id=run_id,
                    source_kind="module",
                    source_component=component,
                    producer_version="1.0.0",
                ),
                clock=clock,
                sequence_factory=sequence_factory,
            )
            for name, component in {
                "identity": "identity-simulator",
                "helpdesk": "helpdesk-simulator",
                "endpoint": "endpoint-ad-simulator",
                "profiles": "osint-profile-initializer",
            }.items()
        }

    @property
    def handlers(self) -> dict[str, Callable[[ScenarioItem, str], AutomationResult]]:
        """Return the fixed action map accepted by ``ScenarioController``."""

        return {action_id: self.handle for action_id in self._ACTION_ITEMS}

    def handle(self, item: ScenarioItem, run_id: str) -> AutomationResult:
        """Execute one controller action through the shared safe-action contract."""

        if run_id != self.run_id or item.action_id not in self._ACTION_ITEMS:
            return AutomationResult(False, "controller/runtime correlation mismatch")
        request = make_action_request(
            exercise_id=self.exercise_id,
            run_id=run_id,
            actor=entity(
                "service_account", "scenario-engine", role="scenario_engine"
            ),
            action_id=item.action_id,
            target=entity("msel_item", item.item_id),
            idempotency_key=f"{run_id}:{item.item_id}",
            dry_run=False,
            timeout_seconds=20,
            clock=self.clock,
        )
        result = self.adapter.execute(request)
        if not result["successful"]:
            return AutomationResult(
                False,
                result["message"],
                {"error_code": result["error_code"], "status": result["status"]},
            )
        evidence_key = f"{run_id}:{item.item_id}"
        if evidence_key not in self._emitted:
            self._emit_evidence(item.action_id)
            self._emitted.add(evidence_key)
        return AutomationResult(
            True,
            result["message"],
            {"effects": result["effects"], "action_request_id": result["request_id"]},
        )

    # Explicit fields keep the evidence mapping reviewable against the matrix.
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _event(
        self,
        source: str,
        event_type: str,
        phase: str,
        actor: Mapping[str, Any],
        action: str,
        target: Mapping[str, Any],
        message: str,
        *,
        outcome: str = "success",
        data: Mapping[str, Any] | None = None,
        objectives: tuple[str, ...] = ("LO1",),
        timestamp: datetime | None = None,
        visibility: str = "participant",
        correlation_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        event = self.builders[source].build(
            event_type=event_type,
            phase=phase,
            actor=actor,
            action=action,
            target=target,
            outcome_status=outcome,
            message=message,
            visibility=visibility,
            dry_run=False,
            safety_controls=("synthetic-data", "reviewed-msel", "allowlisted-target"),
            objective_ids=objectives,
            data=data or {},
            correlation_ids=correlation_ids,
            timestamp=timestamp,
        )
        self.event_sink(event)
        return event

    def _emit_evidence(self, action_id: str) -> None:
        if action_id == "scenario.baseline.load":
            self._event(
                "profiles", "scenario.profiles.initialized", "setup",
                entity("system", "scenario-engine", role="scenario_engine"),
                "scenario.profiles.initialize", entity("service", "IDP01"),
                "Validated synthetic OSINT context loaded into the exercise",
                visibility="facilitator", objectives=(), data=self.profile_summary,
            )
            return
        if action_id == "identity.history.stage":
            self._emit_history()
        elif action_id == "identity.session.replay":
            auth = self._event(
                "identity",
                "identity.authentication.succeeded",
                "identity",
                entity("identity", "sarah", display_name="Sarah Mitchell"),
                "identity.authenticate",
                entity("session", "sess-red-01"),
                "Synthetic authentication reused the compromised session",
                data={"source_ip": "203.0.113.77", "host": "FIN-WS01"},
                objectives=("LO1", "LO2"),
            )
            self._event(
                "endpoint",
                "endpoint.remote_access.succeeded",
                "endpoint_ad",
                entity("session", "sess-red-01"),
                "endpoint.remote_access",
                entity("host", "FIN-WS01"),
                "Compromised session accessed the Finance workstation",
                objectives=("LO1", "LO2"),
                data={
                    "source_ip": "203.0.113.77",
                    "identity_event_id": auth["event_id"],
                },
            )
        elif action_id == "endpoint.discovery.run":
            self._event(
                "endpoint",
                "endpoint.process.discovery",
                "endpoint_ad",
                entity("identity", "sarah"),
                "endpoint.discovery.run",
                entity("host", "FIN-WS01"),
                "Allowlisted process and system discovery completed",
                data={"category": "process-and-system", "command_id": "disc-01"},
                objectives=("LO2",),
            )
            self._event(
                "endpoint",
                "directory.enumeration.completed",
                "endpoint_ad",
                entity("identity", "sarah"),
                "directory.enumerate",
                entity("directory", "DC01"),
                "Synthetic directory enumeration returned baseline objects",
                data={"query_category": "accounts-and-groups", "object_count": 12},
                objectives=("LO2",),
            )
        elif action_id == "identity.persistence.attempt":
            self._event(
                "endpoint",
                "directory.persistence.attempted",
                "endpoint_ad",
                entity("identity", "sarah"),
                "directory.persistence.attempt",
                entity("directory_account", "svc-print-sync"),
                "Designated persistence change was attempted",
                data={"group": "SimCorp-Server-Operators", "state_changed": False},
                objectives=("LO2",),
            )
        elif action_id == "identity.containment.verify":
            self._event(
                "identity",
                "identity.authentication.blocked",
                "endpoint_ad",
                entity("identity", "sarah"),
                "identity.authenticate",
                entity("session", "sess-red-01"),
                "Post-containment authentication was blocked",
                outcome="blocked",
                data={"reason": "session_revoked", "source_ip": "203.0.113.77"},
                objectives=("LO2",),
            )
        elif action_id == "identity.persistence.escalate":
            self._event(
                "endpoint",
                "directory.account.created",
                "endpoint_ad",
                entity("identity", "sarah"),
                "directory.account.create",
                entity("directory_account", "svc-print-sync"),
                "Adverse branch created the designated synthetic account",
                data={"enabled": True},
                objectives=("LO2",),
            )
            self._event(
                "endpoint",
                "directory.group.membership.changed",
                "endpoint_ad",
                entity("directory_account", "svc-print-sync"),
                "directory.group.add_member",
                entity("directory_group", "SimCorp-Server-Operators"),
                "Synthetic account received the designated exercise privilege",
                data={"member": "svc-print-sync"},
                objectives=("LO2",),
            )

    def _emit_history(self) -> None:
        now = self.clock()
        identity = self.profile_context["identity"]
        helpdesk = self.profile_context["helpdesk"]
        self._event(
            "identity",
            "identity.fake_sso.submitted",
            "identity",
            entity("identity", identity["identity_id"], display_name=identity["display_name"]),
            "identity.synthetic_secret.submit",
            entity("service", "simcorp-sso-copy"),
            "Synthetic identity submitted a test-only SSO form",
            data={"landing_id": "landing-001", "source_ip": "203.0.113.77",
                  "profile_id": identity["profile_id"],
                  "contact_candidates": identity["email_candidates"],
                  "field_confidence": identity["field_confidence"]},
            correlation_ids=(identity["profile_id"],),
            timestamp=now - timedelta(minutes=35),
        )
        self._event(
            "helpdesk",
            "helpdesk.identity_reset.completed",
            "identity",
            entity("helpdesk_agent", helpdesk["identity_id"],
                   display_name=helpdesk["display_name"]),
            "helpdesk.identity_reset",
            entity("identity", identity["identity_id"], display_name=identity["display_name"]),
            "Helpdesk completed the synthetic password and MFA reset",
            data={
                "ticket_id": "HD-1042",
                "caller_claim": identity["display_name"],
                "callback_verified": False,
                "caller_employee_id": identity["employee_id"],
                "manager": self.profile_context["manager"]["display_name"],
                "contact_candidates": identity["email_candidates"],
                "field_confidence": identity["field_confidence"],
                "identity_profile_id": identity["profile_id"],
                "helpdesk_profile_id": helpdesk["profile_id"],
            },
            correlation_ids=(identity["profile_id"], helpdesk["profile_id"]),
            timestamp=now - timedelta(minutes=30),
        )
        self._event(
            "identity",
            "identity.factor.registered",
            "identity",
            entity("session", "sess-red-01"),
            "identity.factor.register",
            entity("mfa_factor", "factor-red-01"),
            "Unauthorized synthetic MFA factor was registered",
            data={"identity_id": "sarah", "source_ip": "203.0.113.77"},
            timestamp=now - timedelta(minutes=24),
        )
        self._event(
            "identity",
            "identity.authentication.succeeded",
            "identity",
            entity("identity", "sarah", display_name="Sarah Mitchell"),
            "identity.authenticate",
            entity("service", "IDP01"),
            "Authentication succeeded from the reserved exercise threat source",
            data={"source_ip": "203.0.113.77", "factor_id": "factor-red-01"},
            timestamp=now - timedelta(minutes=20),
        )
        self._event(
            "identity",
            "identity.session.created",
            "identity",
            entity("identity", "sarah"),
            "identity.session.create",
            entity("session", "sess-red-01"),
            "Synthetic compromised session was created",
            data={"source_ip": "203.0.113.77"},
            timestamp=now - timedelta(minutes=19),
        )
        self._event(
            "endpoint",
            "endpoint.remote_access.succeeded",
            "endpoint_ad",
            entity("session", "sess-red-01"),
            "endpoint.remote_access",
            entity("host", "FIN-WS01"),
            "Initial synthetic remote access reached the Finance workstation",
            data={"source_ip": "203.0.113.77", "identity_id": "sarah"},
            objectives=("LO1", "LO2"),
            timestamp=now - timedelta(minutes=15),
        )


class IdentitySliceRun:  # pylint: disable=too-many-instance-attributes
    """Own one correlated controller, simulation, and containment state graph."""

    # Root/fixture/clock inputs remain explicit for startup safety review.
    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        event_sink: Callable[[Mapping[str, Any]], Any],
        run_id: str | None = None,
        scenario_path: Path | str = DEFAULT_SCENARIO_PATH,
        profile_path: Path | str = DEFAULT_PROFILE_PATH,
        impact_root: Path | str | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.event_sink = event_sink
        self.clock = clock
        self.definition = load_scenario(scenario_path)
        self.impact_root = impact_root
        self.impact_enabled = any(item.item_id == "DP4" for item in self.definition.items)
        configuration = self.definition.participant_experience.get("profiles")
        if (not isinstance(configuration, Mapping)
                or set(configuration) != {"seed", "identity_employee_id", "helpdesk_employee_id"}):
            raise ProfileInitializationError(
                "scenario requires reviewed profile initialization fields"
            )
        self.profiles = ProfileCatalog.load(
            profile_path, expected_seed=configuration["seed"],
            identity_employee_id=configuration["identity_employee_id"],
            helpdesk_employee_id=configuration["helpdesk_employee_id"],
        )
        identity = self.profiles.context()["identity"]
        if self.profiles.context()["helpdesk"]["identity_id"] != "tyler":
            raise ProfileInitializationError(
                "helpdesk profile binding must match the reviewed scenario witness"
            )
        sso = self.definition.participant_experience.get("sso")
        mfa = self.definition.participant_experience.get("mfa")
        if not isinstance(sso, Mapping) or not isinstance(mfa, Mapping):
            raise ProfileInitializationError(
                "profile initialization requires SSO/MFA configuration"
            )
        sso_identity = sso.get("identity")
        if not isinstance(sso_identity, Mapping):
            raise ProfileInitializationError(
                "profile initialization requires an SSO identity mapping"
            )
        mfa_identity = mfa.get("identity_id")
        if (identity["identity_id"] != "sarah" or mfa_identity != identity["identity_id"]
                or sso_identity.get("id") != identity["identity_id"]
                or sso_identity.get("username") != identity["username"]
                or sso_identity.get("display_name") != identity["display_name"]):
            raise ProfileInitializationError(
                "profile binding must match the reviewed SSO/MFA identity"
            )
        self.sequencer = EventSequencer()
        self.state_lock = threading.RLock()
        self.identity_state: Any
        self.endpoint_state: Any
        self.identity_adapter: SafeActionAdapter
        self.endpoint_adapter: SafeActionAdapter
        self.automation: IdentitySliceAutomation
        self._initialize(run_id or str(uuid.uuid4()))

    def _run_state(self, _exercise_id: str, _run_id: str) -> str:
        controller = getattr(self, "controller", None)
        return controller.state.value if controller is not None else "ready"

    def _initialize(
        self, run_id: str, *, keep_controller: bool = False, impact_fixture=None,
    ) -> None:
        identity_module = importlib.import_module(
            "modules.04-mfa-fatigue-sim.identity_actions"
        )
        endpoint_module = importlib.import_module(
            "modules.05-lateral-movement.endpoint_actions"
        )
        self.identity_state = identity_module.SyntheticIdentityState.baseline(
            profile_metadata=self.profiles.context()["identity"]
        )
        self.endpoint_state = endpoint_module.EndpointAdState.baseline()

        identity_registry = ActionRegistry()
        identity_module.register_identity_actions(
            identity_registry, self.identity_state, run_id=run_id
        )
        endpoint_registry = ActionRegistry()
        endpoint_module.register_endpoint_actions(
            endpoint_registry, self.endpoint_state, run_id=run_id
        )
        context = {
            "exercise_id": self.definition.exercise_id,
            "run_id": run_id,
            "producer_version": "1.0.0",
        }
        self.identity_adapter = SafeActionAdapter(
            context=EventContext(
                **context,
                source_kind="action_adapter",
                source_component="identity-action-adapter",
            ),
            registry=identity_registry,
            run_state=self._run_state,
            event_sink=self.event_sink,
            clock=self.clock,
            sequence_factory=self.sequencer.next,
        )
        self.endpoint_adapter = SafeActionAdapter(
            context=EventContext(
                **context,
                source_kind="action_adapter",
                source_component="endpoint-ad-action-adapter",
            ),
            registry=endpoint_registry,
            run_state=self._run_state,
            event_sink=self.event_sink,
            clock=self.clock,
            sequence_factory=self.sequencer.next,
        )
        self.automation = IdentitySliceAutomation(
            exercise_id=self.definition.exercise_id,
            run_id=run_id,
            endpoint_state=self.endpoint_state,
            run_state=self._run_state,
            containment_check=self.evaluate_dp2,
            event_sink=self.event_sink,
            sequence_factory=self.sequencer.next,
            clock=self.clock,
            profile_summary=self.profiles.summary(),
        )
        if keep_controller:
            controller = getattr(self, "controller", None)
            if controller is None:
                raise RuntimeError("controller must exist before component rebuild")
            controller.handlers = self.automation.handlers
        else:
            self.controller = ScenarioController(
                self.definition,
                event_sink=self.event_sink,
                handlers=self.automation.handlers,
                run_id=run_id,
                sequence_factory=self.sequencer.next,
                clock=self.clock,
            )
        self.mfa = ScheduledMfa(
            exercise_id=self.definition.exercise_id, run_id=run_id,
            configuration=self.definition.participant_experience["mfa"],
            identity_state=lambda: self.identity_state,
            run_state=lambda: self.controller.state.value,
            elapsed=lambda: self.controller.elapsed_seconds,
            event_sink=self.event_sink, sequence_factory=self.sequencer.next,
            clock=self.clock, state_lock=self.state_lock,
        )
        self.controller.handlers = {
            **self.automation.handlers, "identity.mfa.challenge.deliver": self.mfa.deliver,
        }
        self.cloud_enabled = any(item.item_id == "ACT-05" for item in self.definition.items)
        self.cloud = CloudStage(self, run_id)
        if self.cloud_enabled:
            self.controller.handlers.update(self.cloud.handlers)
        self.impact = (
            ImpactStage(self, run_id, self.impact_root, fixture=impact_fixture)
            if self.impact_enabled else None
        )
        if self.impact:
            self.controller.handlers.update(self.impact.handlers)
        self.controller.time_observers = [self.mfa.advance]

    @property
    def run_id(self) -> str:
        return self.controller.run_id

    # Request fields stay explicit so callers cannot smuggle adapter options.
    # pylint: disable=too-many-arguments
    def submit_action(
        self,
        *,
        actor: Mapping[str, Any],
        action_id: str,
        target: Mapping[str, Any],
        idempotency_key: str,
        parameters: Mapping[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Route one server-authenticated participant action to its safe adapter."""

        with self.state_lock:
            if action_id in IDENTITY_ACTIONS:
                adapter = self.identity_adapter
            elif action_id in ENDPOINT_ACTIONS:
                adapter = self.endpoint_adapter
            elif action_id in CLOUD_ACTIONS and self.cloud_enabled:
                adapter = self.cloud.adapter
            else:
                raise ActionContractError("action is not available in the identity slice")
            request = make_action_request(
                exercise_id=self.definition.exercise_id,
                run_id=self.run_id,
                actor=actor,
                action_id=action_id,
                target=target,
                idempotency_key=idempotency_key,
                parameters=parameters,
                dry_run=dry_run,
                timeout_seconds=15 if action_id in IDENTITY_ACTIONS else 20,
                clock=self.clock,
            )
            result = adapter.execute(request)
            self.mfa.advance(self.controller.elapsed_seconds)
            return result

    def submit_dp1(
        self, submission: IdentityTriageSubmission
    ) -> CheckpointEvaluation:
        """Evaluate a participant DP1 submission and record the result."""

        result = evaluate_identity_triage(submission)
        self.controller.resolve_checkpoint(
            "DP1",
            passed=result.passed,
            evidence_ids=result.evidence_ids,
            reason=result.reason,
            checks=result.checks,
        )
        return result

    def evaluate_dp2(self) -> CheckpointEvaluation:
        """Return the current authoritative identity/endpoint containment result."""

        return evaluate_identity_endpoint_containment(
            self.identity_state.snapshot(), self.endpoint_state.snapshot()
        )

    def resolve_dp2(self) -> CheckpointEvaluation:
        """Evaluate DP2, record it, and execute exactly one branch."""

        result = self.evaluate_dp2()
        self.controller.resolve_checkpoint(
            "DP2",
            passed=result.passed,
            evidence_ids=result.evidence_ids,
            reason=result.reason,
            checks=result.checks,
        )
        return result

    def fail_safe_stop(self, reason: str, *, operator=None) -> None:
        """Attempt every safety latch even when one audit sink is unavailable."""

        # A safety boundary must try remaining latches after any handler/audit error.
        # pylint: disable=broad-exception-caught

        with self.state_lock:
            if not reason.strip():
                raise ControllerError("stop reason cannot be empty")
            if operator is not None and operator.get("role") not in {
                "facilitator", "technical_operator",
            }:
                raise ControllerError("stop requires an exercise-control role")
            if self.controller.state == RunState.COMPLETED:
                raise ControllerError("completed run cannot be stopped")
            errors = []
            if self.controller.state != RunState.STOPPED:
                try:
                    self.controller.fail_safe_stop(reason)
                except Exception as exc:  # Safety cleanup must continue after audit failure.
                    errors.append(exc)
            try:
                self.mfa.stop()
            except Exception as exc:
                errors.append(exc)
            operator = operator or entity("facilitator", "facilitator", role="facilitator")
            adapters = (
                self.automation.adapter,
                self.identity_adapter,
                self.endpoint_adapter,
                self.cloud.adapter,
                self.cloud.automation_adapter,
            )
            if self.impact:
                adapters += (self.impact.adapter, self.impact.automation_adapter)
            for adapter in adapters:
                try:
                    adapter.activate_fail_safe(self.run_id, operator, reason)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise ControllerError(
                    "run stopped; safety cleanup or audit incomplete"
                ) from errors[0]

    def reset(self, *, new_run_id: str | None = None) -> None:
        """Reset app state for a new run after stop/completion."""

        with self.state_lock:
            if self.controller.state not in {RunState.STOPPED, RunState.COMPLETED}:
                raise ActionContractError("run must be stopped or completed before reset")
            if new_run_id == self.run_id:
                raise ActionContractError("reset requires a new run id")
            impact_fixture = None
            if self.impact:
                new_run_id = new_run_id or str(uuid.uuid4())
                self.impact.validate_next_run(new_run_id)
                self.impact.restore_for_reset()
                impact_fixture = self.impact.provision_next_run(new_run_id)
            self.sequencer.reset()
            self.controller.reset(new_run_id=new_run_id)
            self._initialize(
                self.controller.run_id, keep_controller=True,
                impact_fixture=impact_fixture,
            )
