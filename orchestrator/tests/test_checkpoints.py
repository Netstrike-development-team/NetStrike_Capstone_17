"""Objective LO1 and decision point DP1 evaluation tests."""

from __future__ import annotations

from orchestrator.checkpoints import (
    EvidenceReference,
    IdentityTriageSubmission,
    evaluate_identity_triage,
)


def test_dp1_passes_with_three_artifacts_from_two_sources() -> None:
    result = evaluate_identity_triage(
        IdentityTriageSubmission(
            affected_identity="Sarah Mitchell (sarah)",
            classification="Likely account compromise",
            evidence=(
                EvidenceReference("login-001", "identity"),
                EvidenceReference("factor-001", "identity"),
                EvidenceReference("ticket-001", "helpdesk"),
            ),
        )
    )

    assert result.passed is True
    assert all(result.checks.values())
    assert result.evidence_ids == ("factor-001", "login-001", "ticket-001")


def test_dp1_miss_identifies_each_missing_requirement() -> None:
    result = evaluate_identity_triage(
        IdentityTriageSubmission(
            affected_identity="Tyler",
            classification="service outage",
            evidence=(EvidenceReference("ticket-001", "helpdesk"),),
        )
    )

    assert result.passed is False
    assert result.checks == {
        "identity_correct": False,
        "classification_supported": False,
        "artifact_count_met": False,
        "source_diversity_met": False,
    }
    assert "identity_correct" in result.reason


def test_duplicate_evidence_does_not_inflate_artifact_count() -> None:
    duplicate = EvidenceReference("login-001", "identity")
    result = evaluate_identity_triage(
        IdentityTriageSubmission(
            affected_identity="sarah",
            classification="identity compromise",
            evidence=(duplicate, duplicate, duplicate),
        )
    )

    assert result.checks["artifact_count_met"] is False
    assert result.checks["source_diversity_met"] is False
