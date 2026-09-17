"""Allowlisted marker-impact and fixture-recovery safe actions."""

from __future__ import annotations

import hashlib
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

from shared.actions import (
    ActionDefinition,
    ActionEffect,
    ActionExecutionError,
    ActionRegistry,
    ExecutionControl,
    SafeActionAdapter,
)
from shared.events import EventContext

FIXTURE_ID = "FILE01-disposable-fixture"
MARKER_SUFFIX = ".NETSTRIKE-MARKER"
NOTE_NAME = "NETSTRIKE_EXERCISE_NOTE.txt"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IMPACT_ROLES = frozenset({"scenario_engine", "facilitator"})
RECOVERY_ROLES = frozenset({"cloud_responder", "facilitator"})
CONTROL_ROLES = frozenset({"technical_operator", "facilitator"})

FIXTURE_CONTENTS = {
    "approval-queue.txt": b"SYNTHETIC EXERCISE DATA\nApprovals pending: 3\n",
    "billing-export.csv": b"record_id,amount,status\nSIM-001,125.00,approved\n",
    "customer-ledger.json": b'{"synthetic":true,"records":25}\n',
    "payroll-summary.csv": b"department,total\nFinance,12500.00\n",
    "quarter-close-notes.md": b"# Synthetic quarter close\nExercise fixture only.\n",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest(files: Mapping[str, bytes]) -> dict[str, str]:
    return {name: _sha256(content) for name, content in sorted(files.items())}


class ImpactFixture:
    """Filesystem fixture confined to one approved, run-specific directory."""

    def __init__(
        self,
        approved_root: Path | str,
        run_id: str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.approved_root = self._approved_root(approved_root)
        self.run_id = self._validated_run_id(run_id)
        self.run_root = self.approved_root / self.run_id
        self.live_dir = self.run_root / "live"
        self.backup_dir = self.run_root / "known-good"
        self.staging_dir = self.run_root / "staging"
        self.expected_manifest = _manifest(FIXTURE_CONTENTS)
        self.last_report: dict[str, Any] = {}
        self.fault_injector = fault_injector
        self._rollbacks: dict[str, dict[str, Any]] = {}
        self._rollback_sequence = 0
        self._validate_directories()

    @staticmethod
    def _approved_root(value: Path | str) -> Path:
        root = Path(value)
        if not root.is_absolute():
            raise ValueError("approved impact root must be absolute")
        if root.is_symlink() or not root.is_dir():
            raise ValueError("approved impact root must be an existing real directory")
        return root.resolve(strict=True)

    @staticmethod
    def _validated_run_id(run_id: str) -> str:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id is not safe for a run-specific directory")
        return run_id

    @classmethod
    def provision(
        cls,
        approved_root: Path | str,
        run_id: str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> "ImpactFixture":
        """Create a new disposable fixture without overwriting an existing run."""

        root = cls._approved_root(approved_root)
        safe_run_id = cls._validated_run_id(run_id)
        run_root = root / safe_run_id
        if run_root.exists() or run_root.is_symlink():
            raise ValueError("run-specific impact directory already exists")
        try:
            run_root.mkdir(mode=0o700)
            live_dir = run_root / "live"
            backup_dir = run_root / "known-good"
            staging_dir = run_root / "staging"
            for directory in (live_dir, backup_dir, staging_dir):
                directory.mkdir(mode=0o700)
            for name, content in FIXTURE_CONTENTS.items():
                (live_dir / name).write_bytes(content)
                (backup_dir / name).write_bytes(content)
        except Exception:
            shutil.rmtree(run_root, ignore_errors=True)
            raise
        return cls(root, safe_run_id, fault_injector=fault_injector)

    def _validate_directories(self) -> None:
        if self.run_root.is_symlink() or not self.run_root.is_dir():
            raise ValueError("run-specific impact directory is missing or unsafe")
        if self.run_root.resolve(strict=True).parent != self.approved_root:
            raise ValueError("run-specific impact directory escaped approved root")
        for directory in (self.live_dir, self.backup_dir, self.staging_dir):
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("impact fixture directory is missing or unsafe")
            if directory.resolve(strict=True).parent != self.run_root.resolve(
                strict=True
            ):
                raise ValueError("impact fixture directory escaped run root")

    @property
    def _original_names(self) -> frozenset[str]:
        return frozenset(FIXTURE_CONTENTS)

    @property
    def _live_names(self) -> frozenset[str]:
        markers = {f"{name}{MARKER_SUFFIX}" for name in self._original_names}
        return self._original_names | markers | {NOTE_NAME}

    def _inventory(
        self, directory: Path, allowed_names: frozenset[str]
    ) -> dict[str, bytes]:
        try:
            self._validate_directories()
        except ValueError as exc:
            raise ActionExecutionError("unsafe_fixture", str(exc)) from exc
        inventory: dict[str, bytes] = {}
        for path in directory.iterdir():
            if (
                path.name not in allowed_names
                or path.is_symlink()
                or not path.is_file()
            ):
                raise ActionExecutionError(
                    "unsafe_fixture", "Fixture contains an unexpected or unsafe entry"
                )
            if path.resolve(strict=True).parent != directory.resolve(strict=True):
                raise ActionExecutionError(
                    "unsafe_fixture", "Fixture entry escaped its approved directory"
                )
            inventory[path.name] = path.read_bytes()
        return inventory

    def _inventories(self) -> dict[str, dict[str, bytes]]:
        return {
            "live": self._inventory(self.live_dir, self._live_names),
            "backup": self._inventory(self.backup_dir, self._original_names),
            "staging": self._inventory(self.staging_dir, self._original_names),
        }

    def health_mismatches(self) -> tuple[str, ...]:
        """Return baseline filesystem mismatches without following unsafe entries."""

        inventories = self._inventories()
        mismatches = []
        for section in ("live", "backup"):
            if _manifest(inventories[section]) != self.expected_manifest:
                mismatches.append(f"{section}_manifest")
        if inventories["staging"]:
            mismatches.append("staging_not_empty")
        return tuple(mismatches)

    def _capture(self) -> str:
        inventories = self._inventories()
        self._rollback_sequence += 1
        token = f"impact-rb-{self._rollback_sequence}"
        self._rollbacks[token] = {
            "live": inventories["live"],
            "staging": inventories["staging"],
            "last_report": deepcopy(self.last_report),
        }
        return token

    def _replace_inventory(
        self, directory: Path, allowed_names: frozenset[str], files: Mapping[str, bytes]
    ) -> None:
        current = self._inventory(directory, allowed_names)
        for name in current:
            (directory / name).unlink()
        for name, content in files.items():
            (directory / name).write_bytes(content)

    def _restore_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        self._replace_inventory(self.live_dir, self._live_names, snapshot["live"])
        self._replace_inventory(
            self.staging_dir, self._original_names, snapshot["staging"]
        )
        self.last_report = deepcopy(snapshot["last_report"])

    def _step(self, label: str) -> None:
        if self.fault_injector:
            self.fault_injector(label)

    def _marker_content(self, name: str) -> bytes:
        return (
            "NETSTRIKE EXERCISE MARKER - NO ENCRYPTION PERFORMED\n"
            f"Original: {name}\n"
            f"Original-SHA256: {self.expected_manifest[name]}\n"
        ).encode("utf-8")

    def apply_markers(self, variant: str, control: ExecutionControl) -> str:
        """Apply the blocked or realized marker-only MSEL branch."""

        control.checkpoint()
        mismatches = self.health_mismatches()
        if mismatches:
            raise ActionExecutionError(
                "fixture_not_ready", "Impact fixture is not at baseline"
            )
        token = self._capture()
        before = self._inventories()
        try:
            for name in sorted(self._original_names):
                control.checkpoint()
                if variant == "realized":
                    (self.live_dir / name).replace(self.staging_dir / name)
                    self._step(f"moved:{name}")
                marker = self.live_dir / f"{name}{MARKER_SUFFIX}"
                marker.write_bytes(self._marker_content(name))
                self._step(f"marked:{name}")
            if variant == "realized":
                (self.live_dir / NOTE_NAME).write_text(
                    "NETSTRIKE EXERCISE ONLY\n"
                    "Disposable synthetic files were staged by the controller.\n"
                    "No encryption occurred and no payment or contact is required.\n",
                    encoding="utf-8",
                )
                self._step("note-created")
            after = self._inventories()
        except Exception as exc:
            snapshot = self._rollbacks.pop(token)
            self._restore_snapshot(snapshot)
            raise ActionExecutionError(
                "impact_apply_failed", "Marker impact failed and was rolled back"
            ) from exc
        self.last_report = {
            "operation": "impact.marker.apply",
            "variant": variant,
            "before": {name: _manifest(files) for name, files in before.items()},
            "after": {name: _manifest(files) for name, files in after.items()},
        }
        return token

    def restore_fixture(self, control: ExecutionControl) -> str:
        """Restore originals from known-good copies and remove impact artifacts."""

        control.checkpoint()
        inventories = self._inventories()
        if _manifest(inventories["backup"]) != self.expected_manifest:
            raise ActionExecutionError(
                "backup_mismatch", "Known-good fixture does not match its manifest"
            )
        token = self._capture()
        before = inventories
        try:
            self._replace_inventory(self.live_dir, self._live_names, {})
            self._replace_inventory(self.staging_dir, self._original_names, {})
            for name, content in inventories["backup"].items():
                control.checkpoint()
                (self.live_dir / name).write_bytes(content)
                self._step(f"restored:{name}")
            after = self._inventories()
            if _manifest(after["live"]) != self.expected_manifest:
                raise RuntimeError("restored fixture hash mismatch")
        except Exception as exc:
            snapshot = self._rollbacks.pop(token)
            self._restore_snapshot(snapshot)
            raise ActionExecutionError(
                "recovery_failed", "Fixture recovery failed and was rolled back"
            ) from exc
        self.last_report = {
            "operation": "recovery.fixture.restore",
            "before": {name: _manifest(files) for name, files in before.items()},
            "after": {name: _manifest(files) for name, files in after.items()},
        }
        return token

    def rollback(self, token: str, control: ExecutionControl) -> tuple[str, ...]:
        """Restore an exact, one-use pre-action filesystem snapshot."""

        control.checkpoint()
        try:
            snapshot = self._rollbacks.pop(token)
        except KeyError as exc:
            raise ActionExecutionError(
                "invalid_rollback", "Unknown or already-used rollback token"
            ) from exc
        self._restore_snapshot(snapshot)
        return ("restored pre-action disposable fixture",)


def _no_parameters(parameters: Mapping[str, Any]) -> None:
    if parameters:
        raise ValueError("this action accepts no parameters")


def _impact_parameters(parameters: Mapping[str, Any]) -> None:
    if set(parameters) != {"variant"} or parameters["variant"] not in {
        "blocked",
        "realized",
    }:
        raise ValueError("variant must be either blocked or realized")


# The complete mutation surface stays together for role/target policy review.
# pylint: disable=too-many-locals
def register_impact_actions(
    registry: ActionRegistry, fixture: ImpactFixture, *, run_id: str
) -> None:
    """Register marker impact, recovery, reset, and readiness actions."""

    def apply(parameters, _target, control):
        variant = parameters["variant"]
        token = fixture.apply_markers(variant, control)
        return ActionEffect(
            (f"applied {variant} marker-only impact",),
            token,
            metadata={"manifest_report": deepcopy(fixture.last_report)},
        )

    def restore(_parameters, _target, control):
        token = fixture.restore_fixture(control)
        return ActionEffect(
            ("restored disposable fixture from known-good copy",),
            token,
            metadata={"manifest_report": deepcopy(fixture.last_report)},
        )

    def validate(_parameters, _target, control):
        control.checkpoint()
        mismatches = fixture.health_mismatches()
        if mismatches:
            raise ActionExecutionError(
                "fixture_unhealthy",
                "Disposable fixture differs in: " + ", ".join(mismatches),
            )
        return ActionEffect(
            ("validated disposable fixture hashes",),
            metadata={"expected_manifest": deepcopy(fixture.expected_manifest)},
        )

    target = f"fixture_set:{FIXTURE_ID}"
    registry.register(
        ActionDefinition(
            action_id="impact.marker.apply",
            phase="impact_recovery",
            allowed_roles=IMPACT_ROLES,
            allowed_targets=frozenset({target}),
            allowed_run_states=frozenset({"running"}),
            max_timeout_seconds=30,
            expected_effects=("create harmless marker impact",),
            rollback_method="restore pre-impact filesystem snapshot",
            handler=apply,
            rollback_handler=fixture.rollback,
            parameter_validator=_impact_parameters,
        )
    )
    registry.register(
        ActionDefinition(
            action_id="recovery.fixture.restore",
            phase="impact_recovery",
            allowed_roles=RECOVERY_ROLES,
            allowed_targets=frozenset({target}),
            allowed_run_states=frozenset({"running"}),
            max_timeout_seconds=30,
            expected_effects=("restore disposable fixture",),
            rollback_method="restore pre-recovery filesystem snapshot",
            handler=restore,
            rollback_handler=fixture.rollback,
            parameter_validator=_no_parameters,
        )
    )
    registry.register(
        ActionDefinition(
            action_id="recovery.health.validate",
            phase="impact_recovery",
            allowed_roles=RECOVERY_ROLES | CONTROL_ROLES,
            allowed_targets=frozenset({target}),
            allowed_run_states=frozenset({"running", "stopped", "resetting", "ready"}),
            max_timeout_seconds=15,
            expected_effects=("validate disposable fixture hashes",),
            rollback_method="not required for read-only validation",
            handler=validate,
            rollback_handler=lambda _token, _control: (),
            parameter_validator=_no_parameters,
        )
    )
    registry.register(
        ActionDefinition(
            action_id="exercise.impact.reset",
            phase="post_exercise",
            allowed_roles=CONTROL_ROLES,
            allowed_targets=frozenset({f"exercise_run:{run_id}"}),
            allowed_run_states=frozenset({"stopped", "resetting"}),
            max_timeout_seconds=30,
            expected_effects=("restore disposable fixture baseline",),
            rollback_method="restore pre-reset filesystem snapshot",
            handler=restore,
            rollback_handler=fixture.rollback,
            parameter_validator=_no_parameters,
        )
    )
    registry.register(
        ActionDefinition(
            action_id="exercise.impact.readiness.validate",
            phase="setup",
            allowed_roles=CONTROL_ROLES,
            allowed_targets=frozenset({f"exercise_run:{run_id}"}),
            allowed_run_states=frozenset({"setup", "stopped", "resetting", "ready"}),
            max_timeout_seconds=15,
            expected_effects=("validate disposable fixture baseline",),
            rollback_method="not required for read-only validation",
            handler=validate,
            rollback_handler=lambda _token, _control: (),
            parameter_validator=_no_parameters,
        )
    )


def build_impact_adapter(
    *,
    exercise_id: str,
    run_id: str,
    fixture: ImpactFixture,
    run_state: Callable[[str, str], str],
    event_sink: Callable[[Mapping[str, Any]], Any],
) -> SafeActionAdapter:
    """Build a scenario-engine-ready marker-impact adapter."""

    registry = ActionRegistry()
    register_impact_actions(registry, fixture, run_id=run_id)
    return SafeActionAdapter(
        context=EventContext(
            exercise_id=exercise_id,
            run_id=run_id,
            source_kind="action_adapter",
            source_component="marker-impact-action-adapter",
            producer_version="1.0.0",
        ),
        registry=registry,
        run_state=run_state,
        event_sink=event_sink,
    )
