"""Offline, evidence-backed objective review; never mutates checkpoint branches."""

from __future__ import annotations

import hashlib
import html
import json
from copy import deepcopy
from typing import Any, Mapping

from shared.events import EventValidator, redact_sensitive
from .support import support_index

VERSION = "1.0.0"
RATINGS = (
    "performed",
    "performed_with_support",
    "partially_performed",
    "not_performed",
    "not_observed",
)
CHECKPOINT_RUBRICS = {
    "DP1": {
        "objective_ids": ["LO1", "LO2"],
        "system_criteria": [
            "identity_correct",
            "classification_supported",
            "artifact_count_met",
            "source_diversity_met",
        ],
        "meaning": "Identity triage branch; timeline quality remains human review.",
    },
    "DP2": {
        "objective_ids": ["LO2", "LO3"],
        "system_criteria": [
            "malicious_session_revoked",
            "unauthorized_factor_removed",
            "credential_rotated",
            "endpoint_remote_path_isolated",
            "endpoint_evidence_preserved",
        ],
        "meaning": "Identity/endpoint containment branch; sequence and collateral impact need review.",
    },
    "DP3": {
        "objective_ids": ["LO4"],
        "system_criteria": [
            "cloud_steps_observed",
            "principal_identified",
            "key_revoked",
            "approved_policy_restored",
            "exposure_count_supported",
            "transfer_not_overclaimed",
            "exposure_evidence_cited",
        ],
        "meaning": "Mock-cloud containment branch; no real external transfer is inferred.",
    },
    "DP4": {
        "objective_ids": ["LO3", "LO5"],
        "system_criteria": [
            "source_prepared",
            "persistence_removed",
            "impact_task_disabled",
            "host_isolated",
        ],
        "meaning": "Prevention branch only; final recovery observation is separate, not a fifth branch.",
    },
}
OBJECTIVES = {
    "LO1": {
        "title": "Triage the identity incident",
        "checkpoints": ["DP1"],
        "criteria": [
            "Correct identity and classification",
            "Three relevant artifacts from two sources",
            "Within 25 minutes of the first inject",
        ],
        "human_review": ["Artifact relevance and defensible classification"],
        "next_step": "Practise correlating identity and helpdesk evidence before deciding scope.",
    },
    "LO2": {
        "title": "Reconstruct the intrusion",
        "checkpoints": ["DP1", "DP2"],
        "criteria": [
            "Six significant events across the required sources",
            "At least five events correct and materially ordered",
            "Facts distinguished from inference before containment checkpoint",
        ],
        "human_review": [
            "Timeline correctness, ordering, source coverage and fact/inference labels"
        ],
        "next_step": "Build a sourced timeline and clearly separate observations from inference.",
    },
    "LO3": {
        "title": "Contain identity and endpoint access",
        "checkpoints": ["DP2"],
        "criteria": [
            "Session, credential, factor and endpoint containment verified",
            "Evidence preserved before destructive remediation",
            "No more than one unrelated target disrupted",
        ],
        "human_review": ["Evidence-preservation order and collateral disruption"],
        "next_step": "Practise evidence preservation and coordinated containment, then verify the result.",
    },
    "LO4": {
        "title": "Determine and contain cloud data exposure",
        "checkpoints": ["DP3"],
        "criteria": [
            "Correct principal, bucket and evidenced access count",
            "Unauthorized access disabled and approved policy restored",
            "No unsupported external-transfer claim",
        ],
        "human_review": [
            "Bucket identification, evidence interpretation and exposure explanation"
        ],
        "next_step": "Explain confirmed data access separately from unproven external transfer.",
    },
    "LO5": {
        "title": "Recover and communicate",
        "checkpoints": ["DP4"],
        "criteria": [
            "Known-good recovery and health verification by exercise end",
            "Brief covers scope, impact, actions, remaining risk and two prioritized recommendations",
            "Conclusions do not overstate evidence",
        ],
        "human_review": [
            "Truth, clarity, remaining risk and prioritization of recommendations"
        ],
        "next_step": "Validate recovery and write a concise, evidence-supported incident brief.",
    },
}
JUDGMENT_FIELDS = {
    "objective_id",
    "rating",
    "rationale",
    "evidence_ids",
    "expected_revision",
    "override_reason",
    "platform_reason",
    "improvement_actions",
}
ACTION_FIELDS = {"description", "owner", "priority", "target_date"}


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# Explicit run identity and ledger inputs are deliberately not an option map.
# pylint: disable=too-many-arguments
def build_bundle(
    *, exercise_id, run_id, scenario_id, run_state, checkpoint_ids, events, submissions
) -> dict[str, Any]:
    """Freeze redacted events and submissions with a corruption-detection digest."""
    bundle = redact_sensitive(
        {
            "bundle_version": VERSION,
            "rubric_version": VERSION,
            "exercise_id": exercise_id,
            "run_id": run_id,
            "scenario_id": scenario_id,
            "run_state": run_state,
            "checkpoint_ids": sorted(checkpoint_ids),
            "events": sorted(deepcopy(events), key=lambda event: event["sequence"]),
            "submissions": deepcopy(submissions),
        }
    )
    bundle["content_sha256"] = _digest(bundle)
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: Mapping[str, Any]) -> None:
    """Reject mixed runs, invalid ledgers, modified exports and forged reviews."""
    required = {
        "bundle_version",
        "rubric_version",
        "exercise_id",
        "run_id",
        "scenario_id",
        "run_state",
        "checkpoint_ids",
        "events",
        "submissions",
        "content_sha256",
    }
    if not isinstance(bundle, dict) or set(bundle) != required:
        raise ValueError("invalid AAR bundle fields")
    if bundle["bundle_version"] != VERSION or bundle["rubric_version"] != VERSION:
        raise ValueError("unsupported AAR bundle or rubric version")
    for field in ("exercise_id", "run_id", "scenario_id"):
        _text(bundle[field], field, 128)
    if not isinstance(bundle["run_state"], str) or bundle["run_state"] not in {
        "idle",
        "ready",
        "running",
        "paused",
        "stopped",
        "completed",
    }:
        raise ValueError("invalid run state")
    checkpoints = bundle["checkpoint_ids"]
    if (
        not isinstance(checkpoints, list)
        or any(not isinstance(item, str) for item in checkpoints)
        or len(checkpoints) != len(set(checkpoints))
        or not set(checkpoints) <= {"DP1", "DP2", "DP3", "DP4"}
    ):
        raise ValueError("invalid checkpoint scope")
    unsigned = {key: value for key, value in bundle.items() if key != "content_sha256"}
    if bundle["content_sha256"] != _digest(unsigned):
        raise ValueError("AAR bundle integrity check failed")
    event_ids = _event_references(bundle)
    references = _submission_references(bundle["submissions"], event_ids)
    support_index(bundle["events"])
    _validate_judgments(bundle, references)


def _event_references(bundle):
    """Validate canonical events and collect ordered, single-run references."""
    if not isinstance(bundle["events"], list) or len(bundle["events"]) > 100000:
        raise ValueError("invalid event ledger size")
    validator = EventValidator()
    event_ids: set[str] = set()
    sequence = 0
    for event in bundle["events"]:
        if not isinstance(event, dict):
            raise ValueError("invalid canonical event")
        validator.validate(event)
        if (
            event["exercise_id"] != bundle["exercise_id"]
            or event["run_id"] != bundle["run_id"]
            or event["sequence"] <= sequence
            or event["event_id"] in event_ids
        ):
            raise ValueError("AAR requires unique, ordered events from one run")
        event_ids.add(event["event_id"])
        sequence = event["sequence"]
    return event_ids


def _submission_references(submissions, event_ids):
    """Validate the portable, redacted learner submission ledger."""
    if not isinstance(submissions, list) or len(submissions) > 10000:
        raise ValueError("invalid submission ledger size")
    reference_ids = set(event_ids)
    for submission in submissions:
        fields = {
            "submission_id",
            "actor_id",
            "submission_type",
            "submitted_at",
            "payload",
            "result",
        }
        if not isinstance(submission, dict) or set(submission) != fields:
            raise ValueError("invalid submission record")
        identifier = submission["submission_id"]
        if (
            not isinstance(identifier, int)
            or isinstance(identifier, bool)
            or identifier < 1
        ):
            raise ValueError("invalid submission id")
        reference = f"submission:{identifier}"
        if reference in reference_ids:
            raise ValueError("duplicate submission id")
        reference_ids.add(reference)
        for field in ("actor_id", "submission_type", "submitted_at"):
            _text(submission[field], field, 256)
        if not isinstance(submission["payload"], dict) or not isinstance(
            submission["result"], dict
        ):
            raise ValueError("invalid submission payload")
    return reference_ids


def _validate_judgments(bundle, reference_ids):
    """Replay revisions against earlier evidence and authoritative run observations."""
    judgments: dict[str, dict] = {}
    earlier_ids = {item for item in reference_ids if item.startswith("submission:")}
    for event in bundle["events"]:
        if event["event_type"] == "evaluation.objective.judged":
            if (
                event["actor"].get("role") not in {"evaluator", "facilitator"}
                or event["actor"]["type"] != "facilitator"
                or event["visibility"] != "evaluator"
            ):
                raise ValueError(
                    "objective judgment must be attributable to an evaluator"
                )
            data = event["data"]
            if set(data) != JUDGMENT_FIELDS | {"revision", "supersedes_event_id"}:
                raise ValueError("invalid persisted judgment fields")
            payload = {field: data.get(field) for field in JUDGMENT_FIELDS}
            if (
                event.get("objective_ids") != [payload["objective_id"]]
                or (event.get("target") or {}).get("id") != payload["objective_id"]
            ):
                raise ValueError("judgment objective binding mismatch")
            previous = judgments.get(payload["objective_id"])
            validate_judgment(
                payload,
                references=earlier_ids,
                previous=previous,
                observation=objective_observation(bundle, payload["objective_id"]),
            )
            if data.get("revision") != payload["expected_revision"] + 1:
                raise ValueError("invalid judgment revision")
            if data.get("supersedes_event_id") != (
                previous["event_id"] if previous else None
            ):
                raise ValueError("invalid judgment supersession")
            judgments[payload["objective_id"]] = {**data, "event_id": event["event_id"]}
        earlier_ids.add(event["event_id"])


def _text(value, name, maximum=2048):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")


# The objective-specific observation paths stay together for rubric review.
# pylint: disable=too-many-branches
def objective_observation(bundle, objective_id) -> dict[str, Any]:
    """Frozen machine observations are evidence, not a final learner rating."""
    if objective_id not in OBJECTIVES:
        raise ValueError("unknown learning objective")
    checkpoint = {"LO1": "DP1", "LO3": "DP2", "LO4": "DP3"}.get(objective_id)
    events = bundle["events"]
    if objective_id == "LO2":
        return {
            "status": "human_review_required",
            "event_ids": [],
            "explanation": "No automatic timeline-quality verifier exists; review learner artifacts.",
        }
    if objective_id == "LO5":
        candidates = [
            event
            for event in events
            if event["event_type"] == "recovery.review.completed"
        ]
        if not candidates:
            return {
                "status": "not_observed",
                "event_ids": [],
                "explanation": "Final recovery observation unavailable.",
            }
        event = candidates[-1]
        passed = event["data"].get("passed")
    else:
        candidates = [
            event
            for event in events
            if event["event_type"] == "scenario.checkpoint.resolved"
            and (event.get("target") or {}).get("id") == checkpoint
        ]
        if not candidates:
            return {
                "status": "not_observed",
                "event_ids": [],
                "explanation": "Checkpoint observation unavailable.",
            }
        if len(candidates) != 1:
            raise ValueError("duplicate checkpoint resolution")
        event = candidates[0]
        passed = event["data"].get("result") == "pass"
        if event["data"].get("result") not in {"pass", "miss"}:
            raise ValueError("invalid checkpoint result")
        if objective_id == "LO1":
            inject_times = [
                item["data"].get("elapsed_seconds")
                for item in events
                if item["event_type"] == "scenario.item.delivered"
                and item["data"].get("item_kind") == "inject"
            ]
            if any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in inject_times
            ):
                raise ValueError("invalid inject elapsed time")
            deadline = min(inject_times) + 1500 if inject_times else None
            elapsed = event["data"].get("elapsed_seconds")
            if deadline is None or not isinstance(elapsed, int):
                return {
                    "status": "not_observed",
                    "event_ids": [event["event_id"]],
                    "explanation": "Identity timing telemetry unavailable.",
                }
            passed = passed and elapsed <= deadline
        if event["data"].get("reason", "").startswith("Verifier state is missing"):
            return {
                "status": "not_observed",
                "event_ids": [event["event_id"]],
                "explanation": "Verifier state missing; platform review required.",
            }
    if not isinstance(passed, bool):
        raise ValueError("invalid frozen observation")
    return {
        "status": "met" if passed else "not_met",
        "event_ids": [event["event_id"]],
        "checks": deepcopy(
            event["data"].get("checks", event["data"].get("verifier_checks", {}))
        ),
        "explanation": "Machine-verifiable subset only; human criteria still require review.",
    }


# Enumerated checks at a single untrusted-input boundary remain explicit.
# pylint: disable=too-many-branches
def validate_judgment(payload, *, references, previous, observation) -> None:
    """Validate a bounded, explained, current-revision human judgment."""
    if not isinstance(payload, dict) or set(payload) != JUDGMENT_FIELDS:
        raise ValueError("invalid evaluator judgment fields")
    if payload["objective_id"] not in OBJECTIVES or payload["rating"] not in RATINGS:
        raise ValueError("invalid objective or rating")
    _text(payload["rationale"], "rationale")
    revision = payload["expected_revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("invalid expected revision")
    if revision != (previous["revision"] if previous else 0):
        raise ValueError("judgment revision conflict; refresh before submitting")
    evidence = payload["evidence_ids"]
    if (
        not isinstance(evidence, list)
        or len(evidence) > 20
        or any(not isinstance(item, str) for item in evidence)
        or len(evidence) != len(set(evidence))
        or not set(evidence) <= references
    ):
        raise ValueError(
            "evidence references must be unique current-run event or submission IDs"
        )
    for field in ("override_reason", "platform_reason"):
        if not isinstance(payload[field], str) or len(payload[field]) > 2048:
            raise ValueError(f"invalid {field}")
    if payload["rating"] == "not_observed":
        _text(payload["platform_reason"], "platform/exercise-control reason")
    elif not evidence:
        raise ValueError("observed ratings require cited evidence")
    positive = payload["rating"] in {"performed", "performed_with_support"}
    if (
        (positive and observation["status"] == "not_met")
        or (
            observation["status"] == "not_observed"
            and payload["rating"] != "not_observed"
        )
        or previous
    ):
        _text(payload["override_reason"], "override/revision reason")
    actions = payload["improvement_actions"]
    if not isinstance(actions, list) or len(actions) > 5:
        raise ValueError("invalid improvement actions")
    for action in actions:
        if not isinstance(action, dict) or set(action) != ACTION_FIELDS:
            raise ValueError("invalid improvement action fields")
        for field in ACTION_FIELDS:
            _text(action[field], field, 512)
        if action["priority"] not in {"high", "medium", "low"}:
            raise ValueError("invalid improvement priority")


def build_report(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Generate a deterministic staff report without a live portal or SIEM."""
    validate_bundle(bundle)
    events = bundle["events"]
    objectives = []
    for identifier, rubric in OBJECTIVES.items():
        history = [
            {
                **event["data"],
                "event_id": event["event_id"],
                "evaluator_id": event["actor"]["id"],
                "timestamp": event["timestamp"],
            }
            for event in events
            if event["event_type"] == "evaluation.objective.judged"
            and event["data"]["objective_id"] == identifier
        ]
        objectives.append(
            {
                "objective_id": identifier,
                **deepcopy(rubric),
                "observation": objective_observation(bundle, identifier),
                "judgment": history[-1] if history else None,
                "history": history,
            }
        )
    reviewed = sum(item["judgment"] is not None for item in objectives)
    terminal = bundle["run_state"] in {"stopped", "completed"}
    return {
        "report_version": VERSION,
        "rubric_version": VERSION,
        "exercise_id": bundle["exercise_id"],
        "run_id": bundle["run_id"],
        "scenario_id": bundle["scenario_id"],
        "run_state": bundle["run_state"],
        "bundle_sha256": bundle["content_sha256"],
        "status": "reviewed" if reviewed == 5 and terminal else "provisional",
        "reviewed_objectives": reviewed,
        "objective_count": 5,
        "scope_note": "Local synthetic observations; not confirmation of Cyber Range or Splunk acceptance.",
        "assessment_weights": {
            "investigation_evidence": 40,
            "containment_and_recovery": 35,
            "rationale_and_communication": 15,
            "timeliness": 10,
        },
        "aggregate_score": None,
        "aggregate_note": "Charter dimension weights retained; no numeric grade until criterion weights and evaluator calibration are approved.",
        "objectives": objectives,
        "checkpoint_rubrics": {
            identifier: {
                **deepcopy(rubric),
                "in_scenario": identifier in bundle["checkpoint_ids"],
            }
            for identifier, rubric in CHECKPOINT_RUBRICS.items()
        },
        "checkpoint_path": [
            {
                "checkpoint_id": (event.get("target") or {}).get("id"),
                "result": event["data"]["result"],
                "event_id": event["event_id"],
                "elapsed_seconds": event["data"].get("elapsed_seconds"),
                "verifier_checks": deepcopy(event["data"].get("verifier_checks", {})),
            }
            for event in events
            if event["event_type"] == "scenario.checkpoint.resolved"
        ],
        "timeline": [
            {
                "event_id": event["event_id"],
                "sequence": event["sequence"],
                "timestamp": event["timestamp"],
                "event_type": event["event_type"],
                "actor_id": event["actor"]["id"],
                "message": event["message"],
                "elapsed_seconds": event["data"].get("elapsed_seconds"),
            }
            for event in events
        ],
        "submissions": deepcopy(bundle["submissions"]),
        "support_requests": support_index(events),
        "support_note": "Human assistance labels are evidence, not automatic objective ratings.",
        "platform_observations": [
            {
                "objective_id": item["objective_id"],
                "reason": item["judgment"]["platform_reason"],
            }
            for item in objectives
            if item["judgment"] and item["judgment"]["rating"] == "not_observed"
        ],
        "improvement_actions": [
            {"objective_id": item["objective_id"], **action}
            for item in objectives
            if item["judgment"]
            for action in item["judgment"]["improvement_actions"]
        ],
    }


def participant_feedback(report: Mapping[str, Any]) -> dict[str, Any]:
    """Deliberately omit staff text, state, identifiers, branches and answer keys."""
    if report["status"] != "reviewed":
        raise ValueError(
            "feedback requires a terminal run and all five reviewed objectives"
        )
    return {
        "run_id": report["run_id"],
        "status": "reviewed",
        "objectives": [
            {
                "objective_id": item["objective_id"],
                "title": item["title"],
                "rating": item["judgment"]["rating"],
                "next_step": item["next_step"],
            }
            for item in report["objectives"]
        ],
    }


def _md(value: Any) -> str:
    """Neutralize HTML and Markdown metacharacters in staff-authored prose."""
    text = html.escape(str(value)).replace("\n", " ")
    for character in ("\\", "`", "*", "_", "[", "]", "#", "|", ">"):
        text = text.replace(character, "\\" + character)
    return text


def render_markdown(report: Mapping[str, Any]) -> str:
    """Readable AAR with objective results, audit history and corrective owners."""
    lines = [
        "# Operation Silent Spider — After-action review",
        "",
        f"Run: {_md(report['run_id'])} · State: {_md(report['run_state'])} · Report: {_md(report['status'])}",
        "",
        report["scope_note"],
        "",
        report["aggregate_note"],
        "",
        f"Reviewed objectives: {report['reviewed_objectives']}/5",
        "",
        "## Objective results",
        "",
    ]
    for item in report["objectives"]:
        judgment = item["judgment"]
        lines += [
            f"### {item['objective_id']} — {item['title']}",
            "",
            f"Machine observation: {item['observation']['status']}",
            "",
            "Rating: "
            + (judgment["rating"] if judgment else "awaiting evaluator review"),
            "",
        ]
        if judgment:
            lines += [
                f"Evaluator: {_md(judgment['evaluator_id'])} · Revision {judgment['revision']} · {_md(judgment['timestamp'])}",
                "",
                "Rationale: " + _md(judgment["rationale"]),
                "",
                "Evidence: "
                + _md(", ".join(judgment["evidence_ids"]) or "not observed"),
                "",
            ]
            for field in ("override_reason", "platform_reason"):
                if judgment[field]:
                    lines += [
                        f"{field.replace('_', ' ').title()}: {_md(judgment[field])}",
                        "",
                    ]
            if len(item["history"]) > 1:
                lines += ["Review history:", ""]
                for previous in item["history"]:
                    lines += [
                        f"- Revision {previous['revision']}: {_md(previous['rating'])} by {_md(previous['evaluator_id'])}; {_md(previous['rationale'])}; change reason: {_md(previous['override_reason'])}"
                    ]
                lines += [""]
    lines += ["## Human assistance", "", report["support_note"], ""]
    for request in report["support_requests"]:
        lines += [
            f"- Request {_md(request['request_id'])} by {_md(request['requester_id'])} "
            f"for {_md(request['objective_id'])} at {request['elapsed_seconds']} seconds: "
            + _md(request["question"]),
        ]
        reply = request["response"]
        if reply:
            lines += [
                f"  - {_md(reply['kind'])} by {_md(reply['responder_id'])} at "
                f"{reply['elapsed_seconds']} seconds; event {_md(reply['event_id'])}; "
                f"scope {_md(', '.join(reply['objective_ids']))}: " + _md(reply["text"]),
            ]
        else:
            lines += ["  - No staff reply recorded; request alone does not prove assistance was given."]
    if not report["support_requests"]:
        lines += ["No portal support requests recorded; off-platform assistance is not excluded."]
    lines += ["", "## Corrective actions", ""]
    for action in report["improvement_actions"]:
        lines += [
            f"- {action['objective_id']}: {_md(action['description'])} — owner {_md(action['owner'])}, priority {_md(action['priority'])}, target {_md(action['target_date'])}"
        ]
    if not report["improvement_actions"]:
        lines += ["No corrective actions recorded."]
    lines += ["", "## Checkpoint path", ""]
    for checkpoint in report["checkpoint_path"]:
        lines += [
            f"- {_md(checkpoint['checkpoint_id'])}: {_md(checkpoint['result'])} at {checkpoint['elapsed_seconds']} seconds; event {_md(checkpoint['event_id'])}"
        ]
    lines += ["", "## Facilitator timeline (ingestion order)", ""]
    for event in report["timeline"]:
        lines += [
            f"- #{event['sequence']} {_md(event['timestamp'])} · {_md(event['event_type'])} · {_md(event['message'])} · {_md(event['event_id'])}"
        ]
    return "\n".join(lines) + "\n"
