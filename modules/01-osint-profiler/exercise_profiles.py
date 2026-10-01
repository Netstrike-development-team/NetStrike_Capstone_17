"""Export the reviewed local OSINT fixture in the strict exercise input format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shared.profiles import ProfileCatalog, profile_id, validate_seed

from .connectors import LinkedInConnector
from .extractors import extract_identity, infer_email_candidates

DEFAULT_SEED = "silent-spider-profiles-v1"


def build_exercise_bundle(seed: str = DEFAULT_SEED) -> dict:
    """Reuse existing local identity/email extractors without real contact data."""

    validate_seed(seed)
    profiles = []
    for record in LinkedInConnector().scrape():
        identity = extract_identity(record)
        employee_id = record["data"]["id"]
        candidates = infer_email_candidates(identity["first"], identity["last"], [],
                                            domain="simcorp.test")
        for candidate in candidates:
            # A guessed pattern is not an explicit observed email address.
            candidate["confidence"] = "inferred"
        profiles.append({
            "schema_version": "1.0.0", "synthetic": True,
            "id": profile_id(seed, employee_id), "employee_id": employee_id,
            "name": identity["name"], "title": identity["title"],
            "role_group": identity["role_group"], "department": identity["department"],
            "manager": identity["manager"],
            "username": f"{identity['first'].lower()}@simcorp.test",
            "email_candidates": candidates,
            "phone_numbers": [],  # No personal contact numbers are inferred or imported.
            "source_id": record["source_id"],
            "confidence": {"name": "explicit", "role": "explicit",
                           "manager": "explicit" if identity["manager"] else "unknown",
                           "username": "configured"},
        })
    bundle = {"schema_version": "1.0.0", "seed": seed,
              "profiles": sorted(profiles, key=lambda profile: profile["employee_id"])}
    ProfileCatalog(bundle, expected_seed=seed, identity_employee_id="emp_001",
                   helpdesk_employee_id="emp_005")
    return bundle


def main() -> None:
    """Explicit CLI output; never silently normalize an arbitrary imported profile."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output", type=Path)
    output.add_argument("--stdout", action="store_true")
    arguments = parser.parse_args()
    serialized = json.dumps(build_exercise_bundle(arguments.seed), indent=2) + "\n"
    if arguments.stdout:
        print(serialized, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
