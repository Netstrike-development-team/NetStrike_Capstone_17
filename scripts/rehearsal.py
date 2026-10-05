"""Zero-network developer rehearsals of the real local full-play services.

No learner rating, live Splunk acceptance or VM-snapshot restoration is implied.
Preview is inert; execution writes only into a newly created output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import itertools
import json
import re
import platform
import shutil

# Optional fixed, read-only Git provenance commands.
import subprocess  # nosec B404
import sys
import uuid
from dataclasses import asdict, dataclass
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Direct-file execution adds the repository before importing its packages.
# pylint: disable=wrong-import-position
from dashboard.auth import PortalPrincipal
from dashboard.service import PortalService
from dashboard.store import PortalStore
from orchestrator.aar import build_bundle, build_report, render_markdown
from orchestrator.controller import ControllerError, ItemStatus, RunState
from orchestrator.evidence import render_jsonl
from orchestrator.impact import FULL_SCENARIO_PATH, ROOT_CONTENT, ROOT_MARKER
from shared.events import EventValidator

# pylint: enable=wrong-import-position

VERSION = "1.0.0"
FILES = (
    "events.jsonl",
    "reset-events.jsonl",
    "run-review-bundle.json",
    "after-action-review.md",
    "result.json",
)
MAX_FILE_BYTES = 20 * 1024 * 1024
FIXTURE = "FILE01-disposable-fixture"
BUCKET = "simcorp-customer-exports"
PERSONAS = {
    role: PortalPrincipal(f"rehearsal-{role}", role)
    for role in (
        "soc_analyst",
        "identity_responder",
        "endpoint_responder",
        "cloud_responder",
    )
}
LIMITS = [
    "Automated developer personas, not representative learners or evaluators.",
    "Accelerated local exercise clock; no live Splunk, network or real identities.",
    "Application reset only, not a Cyber Range VM snapshot restore.",
    "Provisional AARs only; no human judgments or calibration are manufactured.",
    "Checksums detect changes but are not signatures or external acceptance.",
]


@dataclass(frozen=True)
class Case:
    """A fixed, reviewed developer path; IDs are never arbitrary filesystem paths."""

    case_id: str
    dp1: bool = True
    dp2: bool = False
    dp3: bool = False
    dp4: bool = False
    mode: str = "nominal"


def cases() -> dict[str, Case]:
    """Sixteen checkpoint combinations plus eight control/fault demonstrations."""
    result = {}
    for outcomes in itertools.product((True, False), repeat=4):
        name = "path-" + "-".join("pass" if value else "miss" for value in outcomes)
        result[name] = Case(name, *outcomes)
    for mode in (
        "partial-cloud-control",
        "partial-impact-control",
        "missing-cloud-source",
        "cloud-telemetry-fault",
        "missing-impact-source",
        "impact-write-fault",
        "stop-during-impact",
        "recovery-write-fault",
    ):
        result[mode] = Case(mode, mode=mode)
    return result


def plan(case_ids=None) -> dict:
    """List the reviewed paths without creating a runtime or touching files."""
    selected = select_cases(case_ids)
    return {
        "package_version": VERSION,
        "developer_rehearsal_only": True,
        "writes_performed": False,
        "cases": [asdict(case) for case in selected],
        "limitations": LIMITS,
    }


def select_cases(case_ids=None) -> list[Case]:
    catalog = cases()
    identifiers = list(case_ids) if case_ids is not None else list(catalog)
    if (
        not identifiers
        or len(identifiers) != len(set(identifiers))
        or any(identifier not in catalog for identifier in identifiers)
    ):
        raise ValueError("select unique, known rehearsal case IDs")
    return [catalog[identifier] for identifier in identifiers]


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _write(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as output:
        output.write(content)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(fixture) -> dict:
    """Checksum proof for this instance's allowlisted decoy tree only."""
    fixture.inspect()  # Reject unexpected files, links and unsafe directory state.
    return {
        str(path.relative_to(fixture.run_root)): _sha(path)
        for path in sorted(fixture.run_root.rglob("*"))
        if path.is_file()
    }


def _source() -> dict:
    """Record revision when Git is available, plus exact relevant source hashes."""
    paths = [
        "scripts/rehearsal.py",
        "dashboard/service.py",
        "dashboard/configuration.py",
        "dashboard/preflight.py",
        "dashboard/__init__.py",
        "dashboard/clock.py",
        "dashboard/support.py",
        "dashboard/static/support.js",
        "dashboard/static/staff-operations.js",
        "dashboard/static/review-archives.js",
        "dashboard/static/common.js",
        "dashboard/static/participant.html",
        "dashboard/static/participant.js",
        "dashboard/static/facilitator.html",
        "dashboard/static/facilitator.js",
        "dashboard/static/evaluator.html",
        "dashboard/static/evaluator.js",
        "dashboard/static/styles.css",
        "dashboard/app.py",
        "dashboard/readiness.py",
        "dashboard/archive.py",
        "dashboard/store.py",
        "dashboard/evidence.py",
        "orchestrator/aar.py",
        "orchestrator/support.py",
        "orchestrator/controller.py",
        "orchestrator/identity_slice.py",
        "orchestrator/cloud.py",
        "orchestrator/impact.py",
        "orchestrator/mfa.py",
        "orchestrator/checkpoints.py",
        "orchestrator/scenario.py",
        "orchestrator/scheduler.py",
        "orchestrator/scenarios/full-play.v1.json",
        "orchestrator/fixtures/identity-profiles.v1.json",
        "shared/actions.py",
        "shared/events.py",
        "shared/profiles.py",
        "schemas/event.v1.json",
        "schemas/action.v1.json",
        "modules/04-mfa-fatigue-sim/identity_actions.py",
        "modules/05-lateral-movement/endpoint_actions.py",
        "modules/06-cloud-exfil/cloud_actions.py",
        "modules/07-ransomware-sim/impact_actions.py",
    ]
    hashes = {name: _sha(ROOT / name) for name in paths}
    revision = None
    dirty = None
    try:
        git_path = shutil.which("git") or "/usr/bin/git"
        # Fixed arguments, no shell or user input.
        result = subprocess.run(  # nosec B603
            [git_path, "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if re.fullmatch(r"[0-9a-f]{40}", result.stdout.strip()):
            revision = result.stdout.strip()
            # Fixed read-only Git command.
            status = subprocess.run(  # nosec B603
                [git_path, "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if status.returncode == 0:
                dirty = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass  # Exported source directories need not contain Git metadata.
    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "files_sha256": hashes,
    }


class RehearsalFailure(RuntimeError):
    """A technical expectation failed; preserve evidence and return a failing exit."""


class Driver:
    """Exercise real service methods and adapters, not fabricated checkpoint state."""

    def __init__(self, case: Case, directory: Path):
        self.case = case
        self.directory = directory
        self.checks: list[dict] = []
        self.action_sequence = 0
        self.run_id = f"{case.case_id}-{uuid.uuid4().hex[:12]}"
        self.store = PortalStore()
        root = directory / "disposable"
        root.mkdir()
        try:
            self.service = PortalService(
                self.store,
                run_id=self.run_id,
                scenario_path=FULL_SCENARIO_PATH,
                impact_root=root,
            )
        except Exception:
            self.store.close()
            raise
        self.run = self.service.run

    def check(self, name, actual, expected=True):
        self.checks.append(
            {
                "name": name,
                "actual": deepcopy(actual),
                "expected": deepcopy(expected),
                "passed": actual == expected,
            }
        )
        if actual != expected:
            raise RehearsalFailure(
                f"{name}: expected {expected!r}, observed {actual!r}"
            )

    def action(self, action_id, target_type, target_id, role):
        self.action_sequence += 1
        result = self.service.submit_action(
            PERSONAS[role],
            action_id=action_id,
            target_type=target_type,
            target_id=target_id,
            idempotency_key=f"rehearsal-{self.action_sequence}",
            dry_run=False,
        )
        self.check(f"action:{action_id}", result["successful"])
        return result

    def advance(self, seconds):
        self.service.scheduler.advance_to(seconds)

    def blocked(self, operation, checkpoint, reason):
        before = dict(self.run.controller.checkpoint_results)
        try:
            operation()
        except ControllerError as exc:
            self.check(f"{checkpoint}:platform_guard", reason in str(exc))
        else:
            self.check(f"{checkpoint}:platform_guard", False)
        self.check(
            f"{checkpoint}:no_manufactured_result",
            self.run.controller.checkpoint_results,
            before,
        )

    def opening(self):
        if self.case.mode == "missing-impact-source":
            self.run.controller.skip("PRE-03", "Injected local missing source")
            # Deliberate low-level fault injection, not a supported portal bypass.
            self.run.controller.prepare()
            self.service.scheduler.start()
        else:
            staff = PortalPrincipal("rehearsal-facilitator", "facilitator")
            self.service.prepare_run(staff)
            self.service.start_run(staff)
        self.advance(1500)
        signals = self.service.participant_evidence(PERSONAS["soc_analyst"])["signals"]
        identity = [
            signal for signal in signals if signal["event_type"].startswith("identity.")
        ]
        helpdesk = [
            signal for signal in signals if signal["event_type"].startswith("helpdesk.")
        ]
        self.check("triage_sources_available", len(identity) >= 2 and bool(helpdesk))
        evidence = (
            (identity[0]["event_id"], "identity"),
            (identity[1]["event_id"], "identity"),
            (helpdesk[0]["event_id"], "helpdesk"),
        )
        result = self.service.submit_dp1(
            PERSONAS["soc_analyst"],
            affected_identity="sarah",
            classification=(
                "account compromise" if self.case.dp1 else "routine maintenance"
            ),
            evidence=evidence,
        )
        self.check("DP1:observed_result", result["passed"], self.case.dp1)
        timeline = sorted(
            signals[:6], key=lambda signal: (signal["timestamp"], signal["sequence"])
        )
        self.service.submit_timeline(
            PERSONAS["soc_analyst"],
            run_id=self.run_id,
            entries=[
                {
                    "occurred_at": signal["timestamp"],
                    "event_id": signal["event_id"],
                    "statement_type": "fact",
                    "summary": f"Synthetic regression observation: {signal['event_type']}",
                }
                for signal in timeline
            ],
        )
        if self.case.dp2:
            for action_id, target_type, target_id, role in (
                (
                    "evidence.artifact.preserve",
                    "evidence_artifact",
                    "FIN-WS01-discovery-bundle",
                    "endpoint_responder",
                ),
                (
                    "identity.session.revoke",
                    "session",
                    "sess-red-01",
                    "identity_responder",
                ),
                (
                    "identity.factor.remove",
                    "mfa_factor",
                    "factor-red-01",
                    "identity_responder",
                ),
                (
                    "identity.credential.reset",
                    "identity",
                    "sarah",
                    "identity_responder",
                ),
                ("endpoint.host.isolate", "host", "FIN-WS01", "endpoint_responder"),
            ):
                self.action(action_id, target_type, target_id, role)
        self.advance(3600)
        self.check("DP2:observed_result", self.run.resolve_dp2().passed, self.case.dp2)

    def cloud(self):
        if self.case.mode == "missing-cloud-source":
            self.run.controller.skip("ACT-05", "Injected local missing telemetry")
        if self.case.mode == "cloud-telemetry-fault":
            original = self.run.cloud._evidence  # pylint: disable=protected-access

            def emit(action_id):
                if action_id == "cloud.policy.expand":
                    raise RuntimeError("Injected local telemetry-emission fault")
                original(action_id)

            self.run.cloud._evidence = emit  # pylint: disable=protected-access
        self.advance(4500)
        if self.case.mode in {"missing-cloud-source", "cloud-telemetry-fault"}:
            self.advance(5700)
            self.blocked(self.service.resolve_cloud, "DP3", "incomplete")
            return False
        access = [
            event
            for event in self.run.cloud.audit
            if event["event_type"] == "cloud.object.accessed"
        ][-1]
        self.service.submit_cloud_assessment(
            PERSONAS["cloud_responder"],
            principal_id="svc-cloud-backup",
            confirmed_count=access["data"]["confirmed_count"],
            conclusion="mock_access_only",
            evidence_ids=[access["event_id"]],
        )
        if self.case.dp3 or self.case.mode == "partial-cloud-control":
            self.action(
                "cloud.evidence.preserve", "cloud_bucket", BUCKET, "cloud_responder"
            )
            self.action(
                "cloud.key.revoke",
                "cloud_key",
                "svc-cloud-backup-key-01",
                "cloud_responder",
            )
            if self.case.dp3:
                self.action(
                    "cloud.policy.restore", "cloud_bucket", BUCKET, "cloud_responder"
                )
        self.advance(5700)
        self.check(
            "DP3:observed_result", self.service.resolve_cloud().passed, self.case.dp3
        )
        expected_count = (
            5 if self.case.dp3 or self.case.mode == "partial-cloud-control" else 25
        )
        self.check(
            "cloud:actual_access_count",
            self.run.cloud.state.exposure[BUCKET]["confirmed_count"],
            expected_count,
        )
        self.check(
            "cloud:external_transfer_not_invented",
            all(
                event["data"].get("external_transfer_observed") is False
                for event in self.run.cloud.audit
            ),
        )
        return True

    def impact(self):
        if self.case.dp4 or self.case.mode == "partial-impact-control":
            self.action(
                "endpoint.process.stop",
                "process",
                "impact-task-01",
                "endpoint_responder",
            )
            if self.case.dp4:
                self.action(
                    "endpoint.host.isolate", "host", "FIN-WS01", "endpoint_responder"
                )
                self.action(
                    "ad.persistence.remove",
                    "directory_account",
                    "svc-print-sync",
                    "endpoint_responder",
                )
        self.advance(6600)
        if self.case.mode == "missing-impact-source":
            self.blocked(self.service.resolve_impact, "DP4", "not ready")
            return False
        before = _tree(self.run.impact.fixture)
        marked = []
        if self.case.mode in {"impact-write-fault", "stop-during-impact"}:

            def interrupt(label):
                if label.startswith("marked:"):
                    marked.append(label)
                    if self.case.mode == "impact-write-fault" and len(marked) == 2:
                        raise OSError("Injected local marker-write fault")
                    if len(marked) == 2:
                        self.run.fail_safe_stop(
                            "Injected local stop during partial markers"
                        )

            self.run.impact.fixture.fault_injector = interrupt
        self.check(
            "DP4:observed_result", self.service.resolve_impact().passed, self.case.dp4
        )
        if self.case.mode in {"impact-write-fault", "stop-during-impact"}:
            self.check("impact:interrupted_during_second_marker", len(marked), 2)
            self.check(
                "impact:partial_execution_rollback",
                _tree(self.run.impact.fixture),
                before,
            )
            self.check(
                "impact:branch_failure_visible",
                self.run.controller.items["ACT-08B"].status.value,
                "failed",
            )
            if self.case.mode == "stop-during-impact":
                self.check("impact:stop_during_second_marker", len(marked), 2)
                self.check(
                    "impact:controller_stopped",
                    self.run.controller.state.value,
                    "stopped",
                )
            self.run.impact.fixture.fault_injector = None
            return False
        variant = (
            "blocked"
            if self.case.dp4 or self.case.mode == "partial-impact-control"
            else "realized"
        )
        status = self.run.impact.fixture.inspect()
        self.check(
            "impact:actual_variant",
            self.run.impact.fixture.last_report["variant"],
            variant,
        )
        self.check(
            "impact:available_decoys",
            status["available_originals"],
            5 if variant == "blocked" else 0,
        )
        self.check("impact:no_encryption", status["encryption_performed"], False)
        self.check("impact:originals_unchanged", status["originals_unchanged"])
        return True

    def recovery_action(self, action_id):
        return self.service.recover_fixture(
            PERSONAS["cloud_responder"],
            action_id=action_id,
            fixture_id=FIXTURE,
            key=action_id,
            dry_run=False,
        )

    def finish(self):
        if self.case.mode == "recovery-write-fault":
            before = _tree(self.run.impact.fixture)

            def fail(label):
                if label.startswith("restored:"):
                    raise OSError("Injected local restore-write fault")

            self.run.impact.fixture.fault_injector = fail
            result = self.recovery_action("recovery.fixture.restore")
            self.check(
                "recovery:partial_failure_reported",
                result["error_code"],
                "recovery_failed",
            )
            self.check(
                "recovery:partial_write_rollback",
                _tree(self.run.impact.fixture),
                before,
            )
            self.run.impact.fixture.fault_injector = None
            return
        self.check(
            "recovery:restore_succeeded",
            self.recovery_action("recovery.fixture.restore")["successful"],
        )
        self.check(
            "recovery:health_verified",
            self.recovery_action("recovery.health.validate")["successful"],
        )
        self.service.submit_recovery_brief(
            PERSONAS["cloud_responder"],
            {
                "confirmed_scope": "Synthetic identity, endpoint and mock storage evidence.",
                "confirmed_cloud_records": self.run.cloud.state.exposure[BUCKET][
                    "confirmed_count"
                ],
                "business_impact": "Only disposable exercise data was affected.",
                "actions_taken": "Ran the scripted local responses, restored decoys and verified health.",
                "remaining_risk": "Mock access is not proof of external transfer; human review remains required.",
                "recommendations": [
                    "Review synthetic helpdesk verification.",
                    "Review mock service-key privileges.",
                ],
                "evidence_ids": [self.run.impact.validation_event_id],
            },
        )
        self.advance(7800)
        self.check("play:completed", self.run.controller.state.value, "completed")
        self.check(
            "recovery:frozen_observations_passed", self.run.impact.final_review.passed
        )
        self.check(
            "play:no_failed_items",
            [
                identifier
                for identifier, runtime in self.run.controller.items.items()
                if runtime.status == ItemStatus.FAILED
            ],
            [],
        )
        for checkpoint, selected, opposite in (
            ("DP2", "ACT-04A", "ACT-04B"),
            ("DP3", "ACT-07A", "ACT-07B"),
            ("DP4", "ACT-08A", "ACT-08B"),
        ):
            if self.run.controller.checkpoint_results[checkpoint] == "miss":
                selected, opposite = opposite, selected
            self.check(
                f"{checkpoint}:selected_branch_delivered",
                self.run.controller.items[selected].status.value,
                "delivered",
            )
            self.check(
                f"{checkpoint}:opposite_branch_skipped",
                self.run.controller.items[opposite].status.value,
                "skipped",
            )

    def stop(self):
        if self.run.controller.state in {RunState.RUNNING, RunState.PAUSED}:
            self.run.fail_safe_stop(
                "Local rehearsal ended on an expected fault/control boundary"
            )
        self.run.impact.fixture.fault_injector = None

    def reset(self):
        """Restore the old decoys before accepting and inspecting a fresh app run."""
        old_fixture = self.run.impact.fixture
        self.stop()
        terminal = self.run.controller.state.value
        checkpoint_results = dict(self.run.controller.checkpoint_results)
        before_reset = self.service.aar_bundle()
        state = self.service.reset_run(new_run_id=f"{self.run_id}-reset")
        archived = self.service.review_archive(state["reset"]["review_archive_id"])
        self.check(
            "reset:review_archive_preserves_exact_bundle",
            archived["bundle"] == before_reset,
        )
        self.check(
            "reset:review_archive_provisional",
            archived["report"]["status"],
            "provisional",
        )
        self.check(
            "reset:old_decoys_restored", old_fixture.inspect()["baseline_verified"]
        )
        self.check(
            "reset:old_originals_unchanged",
            old_fixture.inspect()["originals_unchanged"],
        )
        self.check("reset:new_ready", state["controller"]["state"], "ready")
        self.check(
            "reset:all_service_baselines",
            all(
                value
                for name, value in state["reset"].items()
                if name.endswith("_verified")
            ),
        )
        self.check(
            "reset:endpoint_ready", self.run.endpoint_state.readiness_mismatches(), ()
        )
        self.check(
            "reset:new_checkpoints_empty", self.run.controller.checkpoint_results, {}
        )
        self.check(
            "reset:new_submissions_empty", self.store.submissions(self.run.run_id), []
        )
        return terminal, checkpoint_results, state["reset"]

    def export(self, terminal, checkpoint_results, reset, error=None):
        events = self.store.events(self.run.definition.exercise_id, self.run_id)
        reset_events = self.store.events(
            self.run.definition.exercise_id, self.run.run_id
        )
        bundle = build_bundle(
            exercise_id=self.run.definition.exercise_id,
            run_id=self.run_id,
            scenario_id=self.run.definition.scenario_id,
            run_state=terminal,
            checkpoint_ids=["DP1", "DP2", "DP3", "DP4"],
            events=events,
            submissions=self.store.submissions(self.run_id),
        )
        report = build_report(bundle)
        self.check("report:no_human_grade_fabricated", report["reviewed_objectives"], 0)
        self.check("report:provisional", report["status"], "provisional")
        if self.case.mode in {"missing-cloud-source", "cloud-telemetry-fault"}:
            self.check(
                "report:missing_cloud_not_observed",
                report["objectives"][3]["observation"]["status"],
                "not_observed",
            )
        if terminal == "stopped":
            self.check(
                "report:missing_final_not_observed",
                report["objectives"][4]["observation"]["status"],
                "not_observed",
            )
        self.check(
            "ledger:single_run_unique_contiguous",
            [event["sequence"] for event in events],
            list(range(1, len(events) + 1)),
        )
        result = {
            "case": asdict(self.case),
            "run_id": self.run_id,
            "reset_run_id": self.run.run_id,
            "terminal_state": terminal,
            "checkpoint_results": checkpoint_results,
            "events_validated": len(events),
            "checks": self.checks,
            "error": error,
            "reset": reset,
            "verified": error is None and all(check["passed"] for check in self.checks),
        }
        _write(self.directory / "events.jsonl", render_jsonl(events))
        _write(self.directory / "reset-events.jsonl", render_jsonl(reset_events))
        _write(self.directory / "run-review-bundle.json", _json(bundle))
        _write(self.directory / "after-action-review.md", render_markdown(report))
        _write(self.directory / "result.json", _json(result))
        return result

    def capture_failure(self, error):
        """Preserve already-persisted events even if reset or report creation failed."""
        for name, run_id in (
            ("events.jsonl", self.run_id),
            ("reset-events.jsonl", self.run.run_id),
        ):
            path = self.directory / name
            if not path.exists():
                _write(
                    path,
                    render_jsonl(
                        self.store.events(self.run.definition.exercise_id, run_id)
                    ),
                )
        _write(
            self.directory / "failure.json",
            _json(
                {
                    "verified": False,
                    "case": asdict(self.case),
                    "error": f"{type(error).__name__}: {error}",
                }
            ),
        )


def _run_case(case: Case, directory: Path) -> dict:
    driver = Driver(case, directory)
    error = None
    try:
        try:
            driver.opening()
            if driver.cloud() and driver.impact():
                driver.finish()
        except (
            Exception
        ) as exc:  # Preserve failed regression evidence; never turn it green.
            error = f"{type(exc).__name__}: {exc}"
        terminal, checkpoint_results, reset = driver.reset()
        return driver.export(terminal, checkpoint_results, reset, error)
    except Exception as exc:
        driver.capture_failure(exc)
        raise
    finally:
        driver.stop()
        driver.store.close()


def run_suite(
    output: Path | str, case_ids=None, *, progress: Callable | None = None
) -> dict:
    """Create one new, bounded local package; existing destinations are refused."""
    selected = select_cases(case_ids)
    destination = Path(output).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("output must be a new directory; overwrites are refused")
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir() or ".git" in parent.parts:
        raise ValueError("output parent must be an existing non-Git-metadata directory")
    destination = parent / destination.name
    source = _source()
    destination.mkdir()
    results = []
    for case in selected:
        directory = destination / case.case_id
        directory.mkdir()
        try:
            result = _run_case(case, directory)
        except Exception as exc:  # Incomplete cases remain failed and inspectable.
            result = {
                "case": asdict(case),
                "verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        files = {
            name: _sha(directory / name)
            for name in FILES
            if (directory / name).is_file()
        }
        if result["verified"]:
            files.update(_fixture_proof(directory, result))
        results.append(
            {
                "case_id": case.case_id,
                "verified": result["verified"],
                "error": result.get("error"),
                "files_sha256": files,
            }
        )
        if progress:
            progress(case.case_id, result["verified"])
    manifest = {
        "package_version": VERSION,
        "developer_rehearsal_only": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "test_layer": "in_process_portal_service",
        },
        "limitations": LIMITS,
        "cases": results,
        "verified": all(result["verified"] for result in results),
    }
    _write(destination / "manifest.json", _json(manifest))
    _write(
        destination / "README.md",
        "# Local developer rehearsal evidence\n\n"
        + "\n".join(f"- {limit}" for limit in LIMITS)
        + "\n\n"
        + "Each case retains five disposable decoys per old/new run and source-correlated evidence.\n"
        + "Verify offline with `python scripts/rehearsal.py --verify PATH_TO_PACKAGE`.\n",
    )
    return manifest


def _read(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"package entry must be a regular unlinked file: {path.name}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("package file exceeds review limit")
    return path.read_text(encoding="utf-8")


def _fixture_proof(case_root, result):
    """Independently inspect both retained baselines without modifying either."""
    root = case_root.absolute() / "disposable"
    module = importlib.import_module("modules.07-ransomware-sim.impact_actions")
    run_ids = (result["run_id"], result["reset_run_id"])
    if any(
        not isinstance(value, str) or not module.RUN_ID_PATTERN.fullmatch(value)
        for value in run_ids
    ):
        raise ValueError("unsafe fixture correlation")
    if (
        run_ids[0] == run_ids[1]
        or root.is_symlink()
        or not root.is_dir()
        or {path.name for path in root.iterdir()} != {ROOT_MARKER, *run_ids}
    ):
        raise ValueError("unexpected disposable fixture root")
    if _read(root / ROOT_MARKER).encode("utf-8") != ROOT_CONTENT:
        raise ValueError("invalid disposable root marker")
    hashes = {f"disposable/{ROOT_MARKER}": _sha(root / ROOT_MARKER)}
    for run_id in run_ids:
        fixture = module.ImpactFixture(root, run_id)
        if {path.name for path in fixture.run_root.iterdir()} != {
            "live",
            "known-good",
            "staging",
        }:
            raise ValueError("unexpected fixture entry")
        if not fixture.inspect()["baseline_verified"]:
            raise ValueError("retained old/new decoy baseline is not restored")
        hashes.update(
            {
                f"disposable/{run_id}/{name}": digest
                for name, digest in _tree(fixture).items()
            }
        )
    return hashes


def _verify_outcomes(definition, result, bundle, report):
    """Recompute fixed plan expectations against exported events, not check labels."""
    cloud_fault = definition.mode in {"missing-cloud-source", "cloud-telemetry-fault"}
    observed_count = (
        2 if cloud_fault else 3 if definition.mode == "missing-impact-source" else 4
    )
    expected = {
        f"DP{index}": "pass" if passed else "miss"
        for index, passed in enumerate(
            (definition.dp1, definition.dp2, definition.dp3, definition.dp4), 1
        )
        if index <= observed_count
    }
    actual = {
        item["checkpoint_id"]: item["result"] for item in report["checkpoint_path"]
    }
    if actual != expected or result["checkpoint_results"] != actual:
        raise ValueError("canonical checkpoint path does not match the selected plan")
    complete = definition.mode in {
        "nominal",
        "partial-cloud-control",
        "partial-impact-control",
    }
    terminal = "completed" if complete else "stopped"
    if bundle["run_state"] != terminal or result["terminal_state"] != terminal:
        raise ValueError("case terminal state does not match its plan")
    recovery = report["objectives"][4]["observation"]["status"]
    if recovery != ("met" if complete else "not_observed"):
        raise ValueError("recovery observation does not support the case outcome")
    if (
        cloud_fault
        and report["objectives"][3]["observation"]["status"] != "not_observed"
    ):
        raise ValueError("missing cloud source was incorrectly graded")
    if complete:
        access = [
            event
            for event in bundle["events"]
            if event["event_type"] == "cloud.object.accessed"
        ]
        expected_count = (
            5 if definition.dp3 or definition.mode == "partial-cloud-control" else 25
        )
        if not access or access[-1]["data"]["confirmed_count"] != expected_count:
            raise ValueError("cloud exposure does not match real containment")
        markers = [
            event
            for event in bundle["events"]
            if event["event_type"] == "impact.markers.applied"
        ]
        available = (
            5 if definition.dp4 or definition.mode == "partial-impact-control" else 0
        )
        if (
            not markers
            or markers[-1]["data"]["available_originals"] != available
            or markers[-1]["data"]["encryption_performed"] is not False
        ):
            raise ValueError("impact evidence does not match actual task state")
    if result["reset"].get("prior_run_id") != result["run_id"] or any(
        value is not True
        for key, value in result["reset"].items()
        if key.endswith("_verified")
    ):
        raise ValueError("reset observations do not support clean readiness")


def _verify_provenance(manifest):
    """Validate provenance shape without comparing against the reviewer's checkout."""
    source = manifest["source"]
    runtime = manifest["runtime"]
    if (
        not isinstance(source, dict)
        or set(source) != {"git_revision", "working_tree_dirty", "files_sha256"}
        or source["working_tree_dirty"] is not None
        and not isinstance(source["working_tree_dirty"], bool)
        or source["git_revision"] is not None
        and (
            not isinstance(source["git_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", source["git_revision"])
        )
        or not isinstance(source["files_sha256"], dict)
        or not source["files_sha256"]
        or any(
            not isinstance(name, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for name, digest in source["files_sha256"].items()
        )
        or not isinstance(runtime, dict)
        or set(runtime) != {"python", "system", "machine", "test_layer"}
        or any(not isinstance(value, str) or not value for value in runtime.values())
        or runtime["test_layer"] != "in_process_portal_service"
        or not isinstance(manifest["created_at"], str)
    ):
        raise ValueError("invalid rehearsal provenance")
    datetime.fromisoformat(manifest["created_at"])


def _verify_result_shape(result):
    """Reject malformed summaries before using their nested technical fields."""
    fields = {
        "case",
        "run_id",
        "reset_run_id",
        "terminal_state",
        "checkpoint_results",
        "events_validated",
        "checks",
        "error",
        "reset",
        "verified",
    }
    if (
        not isinstance(result, dict)
        or set(result) != fields
        or not isinstance(result["checkpoint_results"], dict)
        or not isinstance(result["reset"], dict)
        or type(result["events_validated"]) is not int
        or result["events_validated"] < 1
        or not isinstance(result["checks"], list)
        or not result["checks"]
        or any(
            not isinstance(check, dict)
            or set(check) != {"name", "actual", "expected", "passed"}
            or not isinstance(check["name"], str)
            for check in result["checks"]
        )
    ):
        raise ValueError("malformed case result")


def verify_package(directory: Path | str) -> dict:
    """Read-only independent ledger/AAR verification; live database not required."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("package must be a real directory")
    manifest = json.loads(_read(root / "manifest.json"))
    fields = {
        "package_version",
        "developer_rehearsal_only",
        "created_at",
        "source",
        "runtime",
        "limitations",
        "cases",
        "verified",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != fields
        or manifest.get("package_version") != VERSION
        or manifest.get("developer_rehearsal_only") is not True
        or manifest.get("limitations") != LIMITS
    ):
        raise ValueError("unsupported rehearsal package")
    _verify_provenance(manifest)
    if (
        not isinstance(manifest["cases"], list)
        or not 1 <= len(manifest["cases"]) <= len(cases())
        or any(
            not isinstance(item, dict)
            or set(item) != {"case_id", "verified", "error", "files_sha256"}
            for item in manifest["cases"]
        )
    ):
        raise ValueError("invalid rehearsal case manifest")
    selected = select_cases([item["case_id"] for item in manifest["cases"]])
    if manifest.get("verified") is not True:
        raise ValueError("rehearsal package contains failed cases")
    total_events = 0
    validator = EventValidator()
    for definition, item in zip(selected, manifest["cases"]):
        case_root = root / definition.case_id
        if case_root.is_symlink() or not case_root.is_dir():
            raise ValueError("case must be a real directory")
        if not isinstance(item["files_sha256"], dict) or item["verified"] is not True:
            raise ValueError("case artifacts are incomplete or failed")
        for name in FILES:
            _read(case_root / name)
            if name not in item["files_sha256"]:
                raise ValueError("case artifact missing from manifest")
            if _sha(case_root / name) != item["files_sha256"][name]:
                raise ValueError(f"case checksum mismatch: {definition.case_id}/{name}")
        result = json.loads(_read(case_root / "result.json"))
        _verify_result_shape(result)
        if (
            not isinstance(result, dict)
            or result["case"] != asdict(definition)
            or result["verified"] is not True
            or result["error"] is not None
            or not isinstance(result["checks"], list)
            or not result["checks"]
            or any(
                not isinstance(check, dict)
                or check["actual"] != check["expected"]
                or check["passed"] is not True
                for check in result["checks"]
            )
        ):
            raise ValueError("case checks do not support verification")
        fixture_hashes = _fixture_proof(case_root, result)
        if set(item["files_sha256"]) != set(FILES) | set(fixture_hashes):
            raise ValueError("unexpected case artifact path")
        if any(
            item["files_sha256"][name] != digest
            for name, digest in fixture_hashes.items()
        ):
            raise ValueError("disposable fixture checksum mismatch")
        bundle = json.loads(_read(case_root / "run-review-bundle.json"))
        report = build_report(bundle)
        _verify_outcomes(definition, result, bundle, report)
        if (
            bundle["run_id"] != result["run_id"]
            or report["status"] != "provisional"
            or report["reviewed_objectives"] != 0
            or render_markdown(report) != _read(case_root / "after-action-review.md")
            or render_jsonl(bundle["events"]) != _read(case_root / "events.jsonl")
        ):
            raise ValueError("offline report/ledger reproduction failed")
        if result["events_validated"] != len(bundle["events"]):
            raise ValueError("event count mismatch")
        reset_events = [
            json.loads(line)
            for line in _read(case_root / "reset-events.jsonl").splitlines()
        ]
        if not reset_events:
            raise ValueError("reset evidence missing")
        for event in reset_events:
            validator.validate(event)
        if (
            any(
                event["run_id"] != result["reset_run_id"]
                or event["exercise_id"] != bundle["exercise_id"]
                for event in reset_events
            )
            or [event["sequence"] for event in reset_events]
            != list(range(1, len(reset_events) + 1))
            or not any(
                event["event_type"] == "scenario.run.reset"
                and event["data"].get("previous_run_id") == result["run_id"]
                for event in reset_events
            )
        ):
            raise ValueError("reset ledger correlation invalid")
        total_events += len(bundle["events"])
    return {
        "verified": True,
        "developer_rehearsal_only": True,
        "cases_verified": len(selected),
        "events_validated": total_events,
        "full_suite": {case.case_id for case in selected} == set(cases()),
        "branch_paths_verified": sum(case.mode == "nominal" for case in selected),
        "control_fault_cases_verified": sum(
            case.mode != "nominal" for case in selected
        ),
        "limitations": LIMITS,
    }


def main(argv=None) -> int:
    """Default preview; explicit local execution or read-only package verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--case", action="append", dest="case_ids", choices=tuple(cases())
    )
    parser.add_argument("--verify", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.verify:
            if arguments.execute or arguments.output or arguments.case_ids:
                parser.error(
                    "--verify cannot be combined with execution/selection options"
                )
            print(_json(verify_package(arguments.verify)), end="")
            return 0
        if not arguments.execute:
            print(_json(plan(arguments.case_ids)), end="")
            return 0
        if arguments.output is None:
            parser.error("--execute requires --output pointing to a new directory")
        manifest = run_suite(
            arguments.output,
            arguments.case_ids,
            progress=lambda name, ok: print(
                f"{name}: {'VERIFIED' if ok else 'FAILED'}"
            ),
        )
        if manifest["verified"]:
            print(_json(verify_package(arguments.output)), end="")
            return 0
        print(
            "Rehearsal failed; partial evidence retained in the selected output directory.",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError, RehearsalFailure) as exc:
        print(f"Cannot verify rehearsal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
