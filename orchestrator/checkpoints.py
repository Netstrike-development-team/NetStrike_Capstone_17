"""Evidence-based checkpoint evaluators kept independent from the SIEM product."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceReference:
    """A participant-cited artifact and the data source used to retrieve it."""

    reference_id: str
    source: str

    def __post_init__(self) -> None:
        if not self.reference_id.strip() or not self.source.strip():
            raise ValueError("evidence references require an id and source")


@dataclass(frozen=True)
class IdentityTriageSubmission:
    """Structured DP1 submission supplied by the participant portal."""

    affected_identity: str
    classification: str
    evidence: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class CheckpointEvaluation:
    """Machine-readable evaluation result suitable for controller evidence."""

    passed: bool
    reason: str
    evidence_ids: tuple[str, ...]
    checks: dict[str, bool]


def _normalized(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def evaluate_identity_triage(
    submission: IdentityTriageSubmission,
    *,
    expected_identity: str = "sarah",
    accepted_classifications: tuple[str, ...] = (
        "account compromise",
        "likely account compromise",
        "identity compromise",
        "likely identity compromise",
    ),
    required_artifacts: int = 3,
    required_sources: int = 2,
) -> CheckpointEvaluation:
    """Evaluate the objective LO1/DP1 requirements without querying Splunk."""

    if required_artifacts < 1 or required_sources < 1:
        raise ValueError("checkpoint thresholds must be positive")

    unique_evidence = {
        (item.reference_id.strip(), item.source.strip().casefold())
        for item in submission.evidence
    }
    evidence_ids = tuple(reference for reference, _ in sorted(unique_evidence))
    sources = {source for _, source in unique_evidence}
    accepted = {_normalized(value) for value in accepted_classifications}
    checks = {
        "identity_correct": _normalized(expected_identity)
        in _normalized(submission.affected_identity),
        "classification_supported": _normalized(submission.classification) in accepted,
        "artifact_count_met": len(unique_evidence) >= required_artifacts,
        "source_diversity_met": len(sources) >= required_sources,
    }
    passed = all(checks.values())
    failed_checks = [name for name, succeeded in checks.items() if not succeeded]
    reason = (
        "Correct identity, classification, artifact count, and source diversity"
        if passed
        else "Missing checkpoint requirements: " + ", ".join(failed_checks)
    )
    return CheckpointEvaluation(
        passed=passed,
        reason=reason,
        evidence_ids=evidence_ids,
        checks=checks,
    )
