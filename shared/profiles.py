"""Validated, deterministic, reviewed synthetic OSINT inputs for exercise startup."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = ROOT / "schemas" / "target_profile.v1.json"
APPROVED_ROSTER = ROOT / "modules" / "01-osint-profiler" / "connectors" / "employees.json"
MAX_PROFILE_BYTES = 1024 * 1024
_SEED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ProfileInitializationError(ValueError):
    """Safe field-level startup error that never echoes submitted personal data."""


def profile_id(seed: str, employee_id: str) -> str:
    """Stable source identity independent of list order or exercise run ID."""

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"netstrike:profile:v1:{seed}:{employee_id}"))


def validate_seed(seed: Any) -> str:
    """Require a bounded, stable fixture seed."""

    if not isinstance(seed, str) or not _SEED.fullmatch(seed):
        raise ProfileInitializationError("profile seed must be a bounded exercise identifier")
    return seed


def reviewed_role(title: str) -> str:
    """Use the existing local profiler's role extractor, not a second heuristic."""

    # Numeric/hyphenated module paths must be imported through importlib.
    import importlib  # pylint: disable=import-outside-toplevel
    extractor = importlib.import_module("modules.01-osint-profiler.extractors")
    return extractor.normalise_role_group(title)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileInitializationError("profile JSON contains duplicate fields")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ProfileInitializationError("profile fixture exceeds the size limit")
        return json.loads(raw, object_pairs_hook=_unique_fields)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProfileInitializationError("profile fixture must be readable, bounded JSON") from exc


class ProfileCatalog:
    """Pin approved profile context for one runtime; callers receive copied views."""

    # Keep contract, reviewed-roster, and binding checks in one audit boundary.
    # pylint: disable=too-many-locals
    def __init__(self, payload: Mapping[str, Any], *, expected_seed: str,
                 identity_employee_id: str, helpdesk_employee_id: str) -> None:
        self.seed = validate_seed(expected_seed)
        if (not isinstance(payload, Mapping)
                or set(payload) != {"schema_version", "seed", "profiles"}
                or payload["schema_version"] != "1.0.0"
                or payload["seed"] != self.seed):
            raise ProfileInitializationError("profile bundle version, seed, or fields are invalid")
        profiles = payload["profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 100:
            raise ProfileInitializationError("profile bundle requires 1–100 profiles")
        schema = _read_json(PROFILE_SCHEMA)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        approved = {item["id"]: item for item in _read_json(APPROVED_ROSTER)}
        self._profiles: dict[str, dict[str, Any]] = {}
        for index, profile in enumerate(profiles):
            error = next(validator.iter_errors(profile), None)
            if error is not None:
                if error.validator == "required" and isinstance(profile, Mapping):
                    missing = [name for name in error.validator_value if name not in profile]
                    raise ProfileInitializationError(
                        f"profiles[{index}]: missing required fields: {', '.join(missing)}"
                    )
                location = ".".join(str(part) for part in error.absolute_path)
                raise ProfileInitializationError(
                    f"profiles[{index}].{location or 'required fields'}: invalid v1 profile"
                )
            employee_id = profile["employee_id"]
            if employee_id in self._profiles:
                raise ProfileInitializationError(
                    f"profiles[{index}].employee_id: duplicate identity"
                )
            employee = approved.get(employee_id)
            if employee is None:
                raise ProfileInitializationError(
                    f"profiles[{index}].employee_id: not in reviewed roster"
                )
            self._validate_reviewed(profile, employee, index)
            record = deepcopy(profile)
            record.setdefault("email_candidates", [])
            record.setdefault("phone_numbers", [])
            self._profiles[employee_id] = record
        self._identity = self._binding(identity_employee_id, "identity")
        self._helpdesk = self._binding(helpdesk_employee_id, "helpdesk")
        if self._helpdesk["role_group"] != "Helpdesk":
            raise ProfileInitializationError(
                "helpdesk profile binding must have a reviewed Helpdesk role"
            )
        if self._identity["employee_id"] == self._helpdesk["employee_id"]:
            raise ProfileInitializationError("identity and helpdesk bindings must be different")
        managers = [p for p in self._profiles.values() if p["name"] == self._identity["manager"]]
        if len(managers) != 1:
            raise ProfileInitializationError(
                "identity manager must resolve to one reviewed profile"
            )
        self._manager = managers[0]
        self.fingerprint = hashlib.sha256(json.dumps(
            {"seed": self.seed, "profiles": self.directory()}, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path | str, **options) -> "ProfileCatalog":
        """Read a local file only; there is no URL fetch or profile discovery."""

        return cls(_read_json(Path(path)), **options)

    def _binding(self, employee_id: Any, label: str) -> dict[str, Any]:
        if not isinstance(employee_id, str) or employee_id not in self._profiles:
            raise ProfileInitializationError(f"{label} profile binding is missing")
        return self._profiles[employee_id]

    def _validate_reviewed(self, profile, employee, index) -> None:
        for name in ("name", "title", "department", "manager"):
            if profile[name] != employee[name]:
                raise ProfileInitializationError(
                    f"profiles[{index}].{name}: differs from reviewed roster"
                )
        first, last = employee["first"].lower(), employee["last"].lower()
        expected = {
            "id": profile_id(self.seed, employee["id"]),
            "username": f"{first}@simcorp.test",
            "role_group": reviewed_role(employee["title"]),
        }
        for name, value in expected.items():
            if profile[name] != value:
                raise ProfileInitializationError(
                    f"profiles[{index}].{name}: differs from reviewed mapping"
                )
        manager_confidence = "explicit" if employee["manager"] else "unknown"
        if profile["confidence"]["manager"] != manager_confidence:
            raise ProfileInitializationError(
                f"profiles[{index}].confidence.manager: inaccurate confidence"
            )
        patterns = {"first.last": f"{first}.{last}", "f.last": f"{first[0]}.{last}",
                    "firstlast": f"{first}{last}", "first": first}
        emails = profile.get("email_candidates", [])
        addresses = [candidate["address"] for candidate in emails]
        if len(addresses) != len(set(addresses)):
            raise ProfileInitializationError(
                f"profiles[{index}].email_candidates: duplicate contacts"
            )
        for rank, candidate in enumerate(emails, start=1):
            if (candidate["rank"] != rank or candidate["address"]
                    != f"{patterns[candidate['pattern']]}@simcorp.test"):
                raise ProfileInitializationError(
                    f"profiles[{index}].email_candidates: invalid mapping or rank"
                )

    def directory(self) -> list[dict[str, Any]]:
        """Reviewed directory with confidence; no attack rankings or role bindings."""

        return [self._context(self._profiles[key]) for key in sorted(self._profiles)]

    @staticmethod
    def _context(profile: Mapping[str, Any]) -> dict[str, Any]:
        return {"identity_id": profile["username"].split("@", 1)[0],
                "employee_id": profile["employee_id"], "profile_id": profile["id"],
                "display_name": profile["name"], "username": profile["username"],
                "title": profile["title"], "role_group": profile["role_group"],
                "department": profile["department"], "manager": profile["manager"],
                "email_candidates": deepcopy(profile["email_candidates"]),
                "phone_numbers": deepcopy(profile["phone_numbers"]),
                "field_confidence": {**deepcopy(profile["confidence"]),
                                     "email_candidates": (
                                         "inferred" if profile["email_candidates"] else "unknown"
                                     ),
                                     "phone_numbers": (
                                         "configured" if profile["phone_numbers"] else "unknown"
                                     )}}

    def context(self) -> dict[str, Any]:
        """Bound mock identity, witness, and manager context for evidence generation."""

        return {"identity": self._context(self._identity),
                "helpdesk": self._context(self._helpdesk), "manager": self._context(self._manager)}

    def summary(self) -> dict[str, Any]:
        """Facilitator-only readiness metadata for the pinned fixture."""

        return {"schema_version": "1.0.0", "profile_count": len(self._profiles),
                "catalog_sha256": self.fingerprint, "bindings": self.context()}
