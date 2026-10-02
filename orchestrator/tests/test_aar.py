"""Portable report validation, frozen observations and full-play export."""

from copy import deepcopy

import pytest

from orchestrator.aar import (
    _digest,
    build_bundle,
    build_report,
    objective_observation,
    participant_feedback,
    render_markdown,
    validate_bundle,
    validate_judgment,
)
from orchestrator.checkpoints import EvidenceReference, IdentityTriageSubmission
from orchestrator.identity_slice import IdentitySliceRun
from orchestrator.impact import FULL_SCENARIO_PATH
from shared.events import EventBuilder, EventContext, entity


def factory():
    return EventBuilder(
        EventContext("exercise", "run", "controller", "test-evaluator", "1.0.0")
    )


def event(builder, event_type="scenario.checkpoint.resolved", **overrides):
    payload = {
        "event_type": event_type,
        "phase": "control",
        "actor": entity("system", "controller"),
        "action": "scenario.checkpoint.evaluate",
        "target": entity("msel_item", "DP1"),
        "outcome_status": "success",
        "message": "Test observation",
        "visibility": "evaluator",
        "data": {"result": "pass", "elapsed_seconds": 1500},
        **overrides,
    }
    return builder.build(**payload)


def bundle(events=(), **overrides):
    return build_bundle(
        exercise_id="exercise",
        run_id="run",
        scenario_id="full-play",
        run_state="completed",
        checkpoint_ids=["DP1", "DP2", "DP3", "DP4"],
        events=list(events),
        submissions=[],
        **overrides
    )


def resign(payload):
    payload["content_sha256"] = _digest(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    return payload


def judgment(**overrides):
    return {
        "objective_id": "LO1",
        "rating": "performed",
        "rationale": "Reviewed evidence quality.",
        "evidence_ids": ["evidence"],
        "expected_revision": 0,
        "override_reason": "",
        "platform_reason": "",
        "improvement_actions": [],
        **overrides,
    }


def test_bundle_digest_detects_changes_and_unknown_version():
    valid = bundle()
    changed = deepcopy(valid)
    changed["run_state"] = "stopped"
    with pytest.raises(ValueError, match="integrity"):
        validate_bundle(changed)
    changed["bundle_version"] = "2.0.0"
    with pytest.raises(ValueError, match="version"):
        validate_bundle(resign(changed))


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_run",
        "duplicate_event",
        "unordered",
        "duplicate_sequence",
        "unknown_field",
        "duplicate_checkpoint",
    ],
)
def test_invalid_ledgers_cannot_be_resigned_into_valid_reports(mutation):
    builder = factory()
    valid = bundle(
        [
            event(builder),
            event(builder, "scenario.run.stopped", data={"elapsed_seconds": 7800}),
        ]
    )
    if mutation == "foreign_run":
        valid["events"][0]["run_id"] = "elsewhere"
    elif mutation == "duplicate_event":
        valid["events"][1]["event_id"] = valid["events"][0]["event_id"]
    elif mutation == "unordered":
        valid["events"].reverse()
    elif mutation == "duplicate_sequence":
        valid["events"][1]["sequence"] = 1
    elif mutation == "unknown_field":
        valid["unexpected"] = "field"
    else:
        valid["checkpoint_ids"].append("DP1")
    with pytest.raises(ValueError):
        validate_bundle(resign(valid))


@pytest.mark.parametrize("elapsed,status", [(1500, "met"), (1501, "not_met")])
def test_lo1_timing_uses_exercise_clock_not_wall_clock(elapsed, status):
    builder = factory()
    first = event(
        builder,
        "scenario.item.delivered",
        data={"item_kind": "inject", "elapsed_seconds": 0},
    )
    result = event(
        builder,
        data={
            "result": "pass",
            "elapsed_seconds": elapsed,
            "verifier_checks": {"identity_correct": True},
        },
    )
    observation = objective_observation(bundle([first, result]), "LO1")
    assert observation["status"] == status
    assert observation["checks"] == {"identity_correct": True}


def test_missing_timing_or_verifier_state_is_not_observed():
    builder = factory()
    assert (
        objective_observation(bundle([event(builder)]), "LO1")["status"]
        == "not_observed"
    )
    missing = event(
        builder,
        target=entity("msel_item", "DP2"),
        data={
            "result": "miss",
            "reason": "Verifier state is missing required field: host",
        },
    )
    assert objective_observation(bundle([missing]), "LO3")["status"] == "not_observed"


def test_positive_rating_against_failed_subset_requires_explained_override():
    observation = {"status": "not_met"}
    with pytest.raises(ValueError, match="override"):
        validate_judgment(
            judgment(), references={"evidence"}, previous=None, observation=observation
        )
    validate_judgment(
        judgment(override_reason="Valid alternative response observed and cited."),
        references={"evidence"},
        previous=None,
        observation=observation,
    )


def test_absent_telemetry_cannot_silently_become_learner_failure():
    with pytest.raises(ValueError, match="override"):
        validate_judgment(
            judgment(rating="not_performed"),
            references={"evidence"},
            previous=None,
            observation={"status": "not_observed"},
        )
    validate_judgment(
        judgment(
            rating="not_observed",
            evidence_ids=[],
            platform_reason="Collector unavailable",
        ),
        references=set(),
        previous=None,
        observation={"status": "not_observed"},
    )


def test_unknown_refs_duplicate_refs_and_unexplained_revision_rejected():
    for overrides in (
        {"evidence_ids": ["foreign"]},
        {"evidence_ids": ["evidence", "evidence"]},
        {"expected_revision": 1},
    ):
        with pytest.raises(ValueError):
            validate_judgment(
                judgment(**overrides),
                references={"evidence"},
                previous=None,
                observation={"status": "met"},
            )


def test_forged_actor_or_objective_binding_rejected():
    builder = factory()
    data = {
        **judgment(
            rating="not_observed", evidence_ids=[], platform_reason="No telemetry"
        ),
        "revision": 1,
        "supersedes_event_id": None,
    }
    forged = event(
        builder,
        "evaluation.objective.judged",
        data=data,
        objective_ids=["LO1"],
        target=entity("objective", "LO1"),
    )
    with pytest.raises(ValueError, match="attributable"):
        bundle([forged])
    forged["actor"] = entity("facilitator", "reviewer", role="evaluator")
    forged["objective_ids"] = ["LO2"]
    with pytest.raises(ValueError, match="binding"):
        bundle([forged])


def test_report_deterministic_no_automatic_grade_or_early_feedback():
    exported = bundle()
    assert build_report(exported) == build_report(deepcopy(exported))
    report = build_report(exported)
    assert report["aggregate_score"] is None
    assert sum(report["assessment_weights"].values()) == 100
    assert set(report["checkpoint_rubrics"]) == {"DP1", "DP2", "DP3", "DP4"}
    assert all(item["judgment"] is None for item in report["objectives"])
    with pytest.raises(ValueError):
        participant_feedback(report)


def test_markdown_neutralizes_staff_html_and_links():
    report = build_report(bundle())
    report["timeline"] = [
        {
            "sequence": 1,
            "timestamp": "2026-10-02T00:00:00Z",
            "event_type": "test.message",
            "message": "<script>alert(1)</script> [bad](https://example.com)",
            "event_id": "test",
        }
    ]
    markdown = render_markdown(report)
    assert "<script>" not in markdown and "\\[bad\\]" in markdown


def test_complete_real_full_play_export_includes_all_four_checks_and_final_review(
    tmp_path,
):
    root = tmp_path / "impact"
    root.mkdir()
    events = []
    run = IdentitySliceRun(
        event_sink=events.append,
        run_id="real-aar-play",
        scenario_path=FULL_SCENARIO_PATH,
        impact_root=root,
    )
    run.controller.prepare()
    run.controller.start()
    run.controller.advance_to(1500)
    run.submit_dp1(
        IdentityTriageSubmission(
            "sarah",
            "account compromise",
            (
                EvidenceReference("HD-1042", "helpdesk"),
                EvidenceReference("factor-red-01", "identity"),
                EvidenceReference("sess-red-01", "identity"),
            ),
        )
    )
    run.controller.advance_to(3600)
    run.resolve_dp2()
    run.controller.advance_to(5700)
    run.cloud.resolve()
    run.controller.advance_to(6600)
    run.impact.resolve()
    actor = entity("participant", "recovery", role="cloud_responder")
    for action_id in ("recovery.fixture.restore", "recovery.health.validate"):
        assert run.impact.recover(
            actor=actor,
            action_id=action_id,
            fixture_id="FILE01-disposable-fixture",
            key=action_id,
            dry_run=False,
        )["successful"]
    run.impact.submit_brief(
        {
            "confirmed_scope": "Synthetic fixture",
            "confirmed_cloud_records": 25,
            "business_impact": "Decoy unavailable",
            "actions_taken": "Restored and validated",
            "remaining_risk": "External transfer unproven",
            "recommendations": ["Verify helpdesk", "Restrict keys"],
            "evidence_ids": [run.impact.validation_event_id],
        }
    )
    run.controller.advance_to(7800)
    exported = build_bundle(
        exercise_id=run.definition.exercise_id,
        run_id=run.run_id,
        scenario_id=run.definition.scenario_id,
        run_state=run.controller.state.value,
        checkpoint_ids=["DP1", "DP2", "DP3", "DP4"],
        events=events,
        submissions=[],
    )
    report = build_report(exported)
    assert len(report["checkpoint_path"]) == 4
    assert all(item["verifier_checks"] for item in report["checkpoint_path"])
    assert report["objectives"][4]["observation"]["status"] == "met"
    assert report["objectives"][4]["judgment"] is None
    assert report["status"] == "provisional"
