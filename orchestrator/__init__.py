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
    evaluate_identity_triage,
)
from .scenario import (
    ScenarioDefinition,
    ScenarioDefinitionError,
    ScenarioItem,
    ScenarioTrigger,
    load_scenario,
)

__all__ = [
    "AutomationResult",
    "CheckpointEvaluation",
    "ControllerError",
    "EvidenceReference",
    "IdentityTriageSubmission",
    "ItemStatus",
    "RunState",
    "ScenarioController",
    "ScenarioDefinition",
    "ScenarioDefinitionError",
    "ScenarioItem",
    "ScenarioTrigger",
    "load_scenario",
    "evaluate_identity_triage",
]
