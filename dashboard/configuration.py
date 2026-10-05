"""Read-only application input validation, never runtime or range readiness."""

from __future__ import annotations

import importlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from orchestrator.identity_slice import (
    DEFAULT_PROFILE_PATH, DEFAULT_SCENARIO_PATH, load_reviewed_profiles,
)
from orchestrator.impact import ImpactStage
from orchestrator.mfa import validate_mfa_configuration
from orchestrator.scenario import ScenarioDefinition
from .auth import PortalPrincipal, TokenAuthenticator
from .origin import OriginAllowlist
from .sso import SsoExperienceConfig

MAX_INPUT_BYTES = 1024 * 1024
SCOPES = ("identity", "cloud", "full-play")
ROLES = frozenset({"incident_lead", "soc_analyst", "identity_responder", "endpoint_responder",
                   "cloud_responder", "facilitator", "technical_operator", "evaluator",
                   "simulated_user", "identity_capture_service"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ASSETS = ("participant.html", "facilitator.html", "evaluator.html", "sso.html", "evidence.html",
          "participant-session.js",
          "participant.js", "facilitator.js", "evaluator.js", "sso.js", "evidence.js",
          "common.js", "support.js", "staff-operations.js", "review-archives.js", "styles.css")


class ConfigurationError(ValueError):
    """Safe check codes only; never propagate injected values or raw exceptions."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration field")
        result[key] = value
    return result


def _json(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("invalid configuration size")
    return json.loads(raw, object_pairs_hook=_unique)


def _scenario(filename):
    source = Path(filename)
    if not source.is_file():
        raise ValueError("scenario must be a regular file")
    with source.open("rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("scenario too large")
    parsed = _json(raw.decode("utf-8"))
    if not isinstance(parsed, Mapping):
        raise ValueError("scenario must be an object")
    return ScenarioDefinition.from_dict(parsed)


def _tokens(raw):
    parsed = _json(raw)
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("missing tokens")
    principals = {}
    for credential, record in parsed.items():
        if (not 24 <= len(credential) <= 4096
                or any(ord(char) < 33 or ord(char) == 127 for char in credential)
                or not isinstance(record, dict) or set(record) != {"actor_id", "role"}
                or not isinstance(record["actor_id"], str)
                or not IDENTIFIER.fullmatch(record["actor_id"])
                or not isinstance(record["role"], str) or record["role"] not in ROLES):
            raise ValueError("invalid principal configuration")
        principals[credential] = PortalPrincipal(**record)
    return TokenAuthenticator(principals), frozenset(item.role for item in principals.values())


def _database(value):
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise ValueError("invalid database path")
    if value == ":memory:":
        return value
    target = Path(value)
    if target.is_symlink() or target.exists() and not target.is_file():
        raise ValueError("database path is not a regular target")
    ancestor = target.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ValueError("database ancestor is not a directory")
    return value


@dataclass(frozen=True, repr=False)
class PortalConfiguration:
    """Validated operator inputs; repr deliberately contains no private fields."""

    database: str
    run_id: str | None
    scenario_path: str
    profile_path: str
    impact_root: str | None
    audit_key: bytes = field(repr=False)
    authenticator: TokenAuthenticator = field(repr=False)
    origins: tuple[str, ...]

    @classmethod
    def from_environment(cls):
        """Fail with safe codes before database/runtime construction."""
        report, configuration = inspect_configuration()
        if configuration is None:
            raise ConfigurationError("Application configuration blocked: " + ", ".join(report["blockers"])) from None
        return configuration


def inspect_configuration(environment=None, *, expected_scope=None):
    """Return safe diagnostics and private config; no server/store/fixture creation."""
    env = dict(os.environ if environment is None else environment)
    checks = []

    def probe(name, operation, *, available=True):
        if not available:
            checks.append({"check_id": name, "passed": False, "code": "dependency_blocked"})
            return None
        try:
            result = operation()
        except Exception:  # Fail closed at the operator boundary without echoing private input.
            checks.append({"check_id": name, "passed": False, "code": "invalid_or_unavailable"})
            return None
        checks.append({"check_id": name, "passed": True, "code": "matched"})
        return result

    def audit_key():
        value = env.get("NETSTRIKE_IDENTITY_AUDIT_KEY", "").encode("utf-8")
        if len(value) < 32:
            raise ValueError("audit key too short")
        return value

    def origins():
        values = _json(env.get("NETSTRIKE_SSO_ALLOWED_ORIGINS", ""))
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("origins must be an array")
        return tuple(sorted(OriginAllowlist(values).origins))

    def run_identifier():
        value = env.get("NETSTRIKE_RUN_ID")
        if value is not None and (not isinstance(value, str) or not IDENTIFIER.fullmatch(value)):
            raise ValueError("invalid run identifier")
        return value

    auth = probe("portal_credentials", lambda: _tokens(env.get("NETSTRIKE_PORTAL_TOKENS", "")))
    audit = probe("identity_audit_key", audit_key)
    allowed = probe("sso_origins", origins)
    identifier = probe("run_identifier", run_identifier)
    database = probe("database_target", lambda: _database(env.get("NETSTRIKE_PORTAL_DATABASE", "output/netstrike-portal.sqlite3")))
    scenario_path = env.get("NETSTRIKE_SCENARIO_PATH", str(DEFAULT_SCENARIO_PATH))
    profile_path = env.get("NETSTRIKE_PROFILE_FIXTURE", str(DEFAULT_PROFILE_PATH))
    definition = probe("scenario_definition", lambda: _scenario(scenario_path))
    profiles = probe("reviewed_profile_bindings", lambda: load_reviewed_profiles(definition, profile_path), available=definition is not None)
    probe("sso_experience", lambda: SsoExperienceConfig.from_mapping(definition.participant_experience.get("sso")), available=definition is not None)

    def mfa():
        module = importlib.import_module("modules.04-mfa-fatigue-sim.identity_actions")
        baseline = module.SyntheticIdentityState.baseline(profile_metadata=profiles.context()["identity"])
        return validate_mfa_configuration(definition.participant_experience.get("mfa"), baseline)

    probe("scheduled_mfa_bindings", mfa, available=definition is not None and profiles is not None)
    item_ids = {item.item_id for item in definition.items} if definition else set()
    scope = "full-play" if "DP4" in item_ids else "cloud" if "ACT-05" in item_ids else "identity" if definition else None

    def scope_guard():
        configured = env.get("NETSTRIKE_EXPECTED_SCENARIO_SCOPE")
        for requested in (configured, expected_scope):
            if requested is not None and (requested not in SCOPES or requested != scope):
                raise ValueError("scenario scope does not match operator intent")
        if scope == "full-play" and "ACT-05" not in item_ids:
            raise ValueError("full play requires cloud stage")
        return scope

    probe("expected_scenario_scope", scope_guard, available=definition is not None)
    impact_root = env.get("NETSTRIKE_IMPACT_ROOT")

    def impact():
        if scope != "full-play":
            return "not_enabled"
        if not impact_root:
            raise ValueError("missing impact root")
        root = ImpactStage.inspect_root(impact_root)
        if identifier is not None:
            module = importlib.import_module("modules.07-ransomware-sim.impact_actions")
            if not module.RUN_ID_PATTERN.fullmatch(identifier) or (root / identifier).exists() or (root / identifier).is_symlink():
                raise ValueError("impact run is unsafe or already present")
        return "inspected_only"

    probe("disposable_impact_root", impact, available=definition is not None)

    def assets():
        root = Path(__file__).resolve().parent / "static"
        if not all((root / name).is_file() for name in ASSETS):
            raise ValueError("local portal assets missing")
        return True

    probe("offline_portal_assets", assets)
    blockers = [check["check_id"] for check in checks if not check["passed"]]
    roles = sorted(auth[1]) if auth else []
    report = {"schema_version": "1.0.0", "scope": "application_configuration_only",
              "configuration_valid": not blockers, "read_only": True,
              "selected_scenario_scope": scope, "configured_roles": roles,
              "checks": checks, "blockers": blockers,
              "external_readiness_verified": False, "runtime_readiness_verified": False,
              "not_checked": ["database_integrity_or_run_history", "actual_write_permissions",
                              "runtime_handlers_and_baselines", "supervised_clock",
                              "tls_or_service_account", "vm_targets_dns_ntp", "splunk_ingestion_and_access",
                              "installer_hashes_licenses_and_bundle_provenance", "snapshot_restore", "facilitator_admission"],
              "warnings": ["startup_can_create_or_migrate_database",
                           "preflight_does_not_reserve_run_or_pin_files", "one_process_one_asgi_worker_required"]}
    if scope == "full-play":
        report["warnings"].append("full_play_startup_provisions_five_disposable_decoys")
    if database == ":memory:":
        report["warnings"].append("database_is_ephemeral")
    if auth and not auth[1] & {"facilitator", "technical_operator"}:
        report["warnings"].append("no_staff_control_credential")
    if auth and not auth[1] & {"facilitator", "evaluator"}:
        report["warnings"].append("no_review_credential")
    if scope == "full-play" and auth and "cloud_responder" not in auth[1]:
        report["warnings"].append("no_cloud_recovery_credential")
    configuration = None if blockers else PortalConfiguration(
        database, identifier, str(scenario_path), str(profile_path), impact_root, audit, auth[0], allowed,
    )
    return report, configuration
