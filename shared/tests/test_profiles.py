"""Strict synthetic-profile contract, safety, deterministic context, and errors."""

import importlib
import json
from copy import deepcopy

import pytest

from shared.profiles import MAX_PROFILE_BYTES, ProfileCatalog, ProfileInitializationError

exporter = importlib.import_module("modules.01-osint-profiler.exercise_profiles")


def catalog(bundle=None, **options):
    return ProfileCatalog(bundle if bundle is not None else exporter.build_exercise_bundle(),
                          expected_seed=exporter.DEFAULT_SEED, identity_employee_id="emp_001",
                          helpdesk_employee_id=options.get("helpdesk_employee_id", "emp_005"))


def test_valid_reviewed_bundle_seeds_consistent_context_without_hidden_scores():
    loaded = catalog()
    context = loaded.context()
    assert context["identity"]["identity_id"] == "sarah"
    assert context["identity"]["username"] == "sarah@simcorp.test"
    assert context["helpdesk"]["display_name"] == "Tyler Brennan"
    assert context["manager"]["display_name"] == "James Okafor"
    assert len(loaded.directory()) == 20
    assert "attack_value" not in str(loaded.directory())
    assert context["identity"]["field_confidence"]["email_candidates"] == "inferred"
    assert context["identity"]["field_confidence"]["phone_numbers"] == "unknown"
    assert all(candidate["confidence"] == "inferred" for candidate in context["identity"]["email_candidates"])


def test_order_independent_and_seed_deterministic_but_returns_defensive_copies():
    bundle = exporter.build_exercise_bundle()
    reverse = deepcopy(bundle)
    reverse["profiles"].reverse()
    assert catalog(bundle).directory() == catalog(reverse).directory()
    assert catalog(bundle).fingerprint == catalog(reverse).fingerprint
    loaded = catalog(bundle)
    altered = loaded.context()
    altered["identity"]["display_name"] = "unapproved"
    altered["identity"]["email_candidates"].clear()
    assert loaded.context() == catalog(bundle).context()


def test_partial_optional_contact_data_is_unknown_not_invented():
    bundle = exporter.build_exercise_bundle()
    for profile in bundle["profiles"]:
        profile.pop("email_candidates")
        profile.pop("phone_numbers")
    identity = catalog(bundle).context()["identity"]
    assert identity["email_candidates"] == []
    assert identity["field_confidence"]["email_candidates"] == "unknown"


@pytest.mark.parametrize("profiles", [[], [None] * 101])
def test_empty_and_excessive_profile_counts_are_rejected(profiles):
    bundle = exporter.build_exercise_bundle()
    bundle["profiles"] = profiles
    with pytest.raises(ProfileInitializationError, match="1–100"):
        catalog(bundle)


@pytest.mark.parametrize("payload", [None, [], {}, {"schema_version": "2.0.0", "seed": "bad", "profiles": []}])
def test_invalid_or_empty_bundle_fails_closed(payload):
    with pytest.raises(ProfileInitializationError):
        ProfileCatalog(payload, expected_seed=exporter.DEFAULT_SEED,
                       identity_employee_id="emp_001", helpdesk_employee_id="emp_005")


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2.0.0"), ("synthetic", False), ("name", "Unapproved Real Person"),
    ("employee_id", "emp_999"), ("manager", "Unapproved manager"),
    ("username", "person@real-company.com"), ("username", "wrong@simcorp.test"),
    ("role_group", "Helpdesk"), ("source_id", "https://external.example/profile"),
])
def test_invalid_unapproved_or_external_profile_is_rejected_without_echo(field, value):
    bundle = exporter.build_exercise_bundle()
    bundle["profiles"][0][field] = value
    with pytest.raises(ProfileInitializationError) as error:
        catalog(bundle)
    assert str(value) not in str(error.value)


@pytest.mark.parametrize("change", ["domain", "wrong_person", "confidence", "url", "extra_personal_data", "phone", "rank", "duplicate", "missing_required"])
def test_contact_provenance_and_structure_are_strict(change):
    bundle = exporter.build_exercise_bundle()
    profile = bundle["profiles"][0]
    if change == "domain":
        profile["email_candidates"][0]["address"] = "sarah.mitchell@simcorp.com"
    elif change == "wrong_person":
        profile["email_candidates"][0]["address"] = "someone.else@simcorp.test"
    elif change == "confidence":
        profile["email_candidates"][0]["confidence"] = "explicit"
    elif change == "url":
        profile["external_url"] = "https://outside.example"
    elif change == "extra_personal_data":
        profile["home_address"] = "private address"
    elif change == "phone":
        profile["phone_numbers"] = [{"normalised": "+1-613-123-4567", "label": "helpdesk", "confidence": "configured"}]
    elif change == "rank":
        profile["email_candidates"][0]["rank"] = 2
    elif change == "duplicate":
        bundle["profiles"].append(deepcopy(profile))
    else:
        profile.pop("title")
    with pytest.raises(ProfileInitializationError):
        catalog(bundle)


def test_missing_role_and_manager_bindings_fail():
    bundle = exporter.build_exercise_bundle()
    bundle["profiles"] = [p for p in bundle["profiles"] if p["employee_id"] != "emp_002"]
    with pytest.raises(ProfileInitializationError, match="manager"):
        catalog(bundle)
    with pytest.raises(ProfileInitializationError, match="Helpdesk"):
        catalog(helpdesk_employee_id="emp_002")


def test_file_boundary_rejects_missing_malformed_duplicate_and_oversized_json(tmp_path):
    options = {"expected_seed": exporter.DEFAULT_SEED, "identity_employee_id": "emp_001", "helpdesk_employee_id": "emp_005"}
    with pytest.raises(ProfileInitializationError, match="readable"):
        ProfileCatalog.load(tmp_path / "missing.json", **options)
    path = tmp_path / "input.json"
    for raw in (b"{", b'{"seed":"first","seed":"second"}', b" " * (MAX_PROFILE_BYTES + 1)):
        path.write_bytes(raw)
        with pytest.raises(ProfileInitializationError):
            ProfileCatalog.load(path, **options)
    path.write_text(json.dumps(exporter.build_exercise_bundle()), encoding="utf-8")
    assert len(ProfileCatalog.load(path, **options).directory()) == 20
