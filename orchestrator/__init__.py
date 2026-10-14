"""Scenario orchestration package for Operation Silent Spider."""

from .controller import (
    AutomationResult,
    ControllerError,
    ItemStatus,
    RunState,
    ScenarioController,
)
from .checkpoints import (
    CheckpointEvaluation,
    EvidenceReference,
    IdentityTriageSubmission,
    evaluate_identity_endpoint_containment,
    evaluate_identity_triage,
)
from .scenario import (
    ScenarioDefinition,
    ScenarioDefinitionError,
    ScenarioItem,
    ScenarioTrigger,
    load_scenario,
)
from .identity_slice import IdentitySliceRun
from .scheduler import ScenarioScheduler

__all__ = [
    "AutomationResult",
    "CheckpointEvaluation",
    "ControllerError",
    "EvidenceReference",
    "IdentityTriageSubmission",
    "IdentitySliceRun",
    "ItemStatus",
    "RunState",
    "ScenarioController",
    "ScenarioDefinition",
    "ScenarioDefinitionError",
    "ScenarioItem",
    "ScenarioScheduler",
    "ScenarioTrigger",
    "load_scenario",
    "evaluate_identity_endpoint_containment",
    "evaluate_identity_triage",
]
