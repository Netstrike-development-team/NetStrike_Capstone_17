"""Objective LO1 and decision point DP1 evaluation tests."""

from __future__ import annotations

from orchestrator.checkpoints import (
    EvidenceReference,
    IdentityTriageSubmission,
    evaluate_identity_endpoint_containment,
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


def _containment_state():
    return (
        {
            "sessions": {"sess-red-01": {"active": False}},
            "factors": {"factor-red-01": {"active": False}},
            "identities": {"sarah": {"credential_version": 2}},
        },
        {
            "hosts": {
                "FIN-WS01": {
                    "isolated": True,
                    "remote_path_enabled": False,
                    "controller_visible": True,
                }
            },
            "artifacts": {
                "FIN-WS01-discovery-bundle": {"preserved": True}
            },
        },
    )


def test_dp2_passes_only_when_all_authoritative_state_checks_pass() -> None:
    identity, endpoint = _containment_state()

    result = evaluate_identity_endpoint_containment(identity, endpoint)

    assert result.passed is True
    assert all(result.checks.values())
    assert len(result.evidence_ids) == 5


def test_dp2_reports_each_incomplete_containment_action() -> None:
    identity, endpoint = _containment_state()
    identity["sessions"]["sess-red-01"]["active"] = True
    endpoint["artifacts"]["FIN-WS01-discovery-bundle"]["preserved"] = False

    result = evaluate_identity_endpoint_containment(identity, endpoint)

    assert result.passed is False
    assert result.checks["malicious_session_revoked"] is False
    assert result.checks["endpoint_evidence_preserved"] is False


def test_dp2_missing_verifier_state_is_not_treated_as_participant_failure() -> None:
    result = evaluate_identity_endpoint_containment({}, {})

    assert result.passed is False
    assert result.checks == {"verifier_state_complete": False}
    assert "missing required field" in result.reason
