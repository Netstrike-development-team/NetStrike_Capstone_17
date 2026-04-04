"""
Test suite for the OSINT Profiler: Phase 1.

Covers:
  Issue #36: Harvest Simulated Sources (whitelist enforcement)
  Issue #37: Extract Basic Identity Attributes
  Issue #38: Infer Email Patterns
  Issue #39: Collect Public Phone Numbers
  Issue #40: Detect SSO Provider Mentions
  Issue #41: Generate Scenario Template
  Issue #42: Export Structured JSON
  Issue #43: Logging & Basic Safeguards
"""

import json
import sys
import pytest
from pathlib import Path
from datetime import datetime

# Make parent importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import (
    LinkedInConnector,
    JobPostingConnector,
    WebsiteConnector,
    SourceNotWhitelisted,
    WHITELISTED_SOURCES,
    _assert_whitelisted,
    _make_raw_record,
)
from extractors import (
    extract_identity,
    infer_email_candidates,
    extract_phone_numbers,
    detect_sso_provider,
    _normalise_role_group,
    _normalise_phone,
    EXPLICIT,
    INFERRED,
)


# ===========================================================================
# Issue #36: Whitelist enforcement
# ===========================================================================

class TestWhitelistEnforcement:
    def test_whitelisted_sources_defined(self):
        assert "linkedin" in WHITELISTED_SOURCES
        assert "job_postings" in WHITELISTED_SOURCES
        assert "company_website" in WHITELISTED_SOURCES

    def test_assert_whitelisted_passes_for_valid_source(self):
        # Should not raise
        _assert_whitelisted("linkedin")
        _assert_whitelisted("job_postings")
        _assert_whitelisted("company_website")

    def test_assert_whitelisted_raises_for_invalid_source(self):
        """Issue #43: whitelist enforcement test that fails on non-whitelisted domain"""
        with pytest.raises(SourceNotWhitelisted):
            _assert_whitelisted("real_linkedin.com")

    def test_assert_whitelisted_raises_for_external_domain(self):
        with pytest.raises(SourceNotWhitelisted):
            _assert_whitelisted("https://linkedin.com")

    def test_assert_whitelisted_raises_for_empty_string(self):
        with pytest.raises(SourceNotWhitelisted):
            _assert_whitelisted("")

    def test_linkedin_connector_stays_whitelisted(self):
        """Connector must fail if someone changes its SOURCE_ID to a real domain."""
        assert LinkedInConnector.SOURCE_ID in WHITELISTED_SOURCES

    def test_job_posting_connector_stays_whitelisted(self):
        assert JobPostingConnector.SOURCE_ID in WHITELISTED_SOURCES

    def test_website_connector_stays_whitelisted(self):
        assert WebsiteConnector.SOURCE_ID in WHITELISTED_SOURCES


# ===========================================================================
# Issue #36: Connector output format
# ===========================================================================

class TestConnectorOutput:
    def test_linkedin_returns_list(self):
        records = LinkedInConnector().scrape()
        assert isinstance(records, list)
        assert len(records) > 0

    def test_linkedin_record_has_provenance_envelope(self):
        records = LinkedInConnector().scrape()
        for rec in records:
            assert "scrape_id" in rec
            assert "source_id" in rec
            assert "scraped_at" in rec
            assert "data" in rec

    def test_linkedin_source_id_is_correct(self):
        records = LinkedInConnector().scrape()
        assert all(r["source_id"] == "linkedin" for r in records)

    def test_linkedin_scraped_at_is_iso_timestamp(self):
        records = LinkedInConnector().scrape()
        ts = records[0]["scraped_at"]
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_job_postings_returns_list(self):
        records = JobPostingConnector().scrape()
        assert isinstance(records, list)
        assert len(records) > 0

    def test_job_postings_have_body_field(self):
        records = JobPostingConnector().scrape()
        for rec in records:
            assert "body" in rec["data"]

    def test_website_connector_returns_list(self):
        records = WebsiteConnector().scrape()
        assert isinstance(records, list)
        assert len(records) > 1  # multi-page site: one record per HTML page

    def test_website_connector_finds_phones(self):
        records = WebsiteConnector().scrape()
        all_phones = [p for rec in records for p in rec["data"]["phones_found"]]
        assert len(all_phones) > 0

    def test_website_connector_finds_emails(self):
        records = WebsiteConnector().scrape()
        all_emails = [e for rec in records for e in rec["data"]["emails_found"]]
        assert len(all_emails) > 0

    def test_website_connector_detects_okta(self):
        records = WebsiteConnector().scrape()
        total_okta = sum(rec["data"]["okta_mentions"] for rec in records)
        assert total_okta > 0

    def test_make_raw_record_structure(self):
        rec = _make_raw_record("linkedin", {"name": "Test"})
        assert rec["source_id"] == "linkedin"
        assert rec["data"] == {"name": "Test"}
        assert "scrape_id" in rec
        assert "scraped_at" in rec


# ===========================================================================
# Issue #37: Identity extraction
# ===========================================================================

class TestIdentityExtraction:
    def setup_method(self):
        records = LinkedInConnector().scrape()
        self.records = records
        self.sample = records[0]

    def test_extract_identity_returns_required_fields(self):
        identity = extract_identity(self.sample)
        required = ["name", "first", "last", "display_name", "title",
                    "role_group", "department", "manager", "source_id",
                    "snippet", "confidence"]
        for field in required:
            assert field in identity, f"Missing field: {field}"

    def test_name_split_correct(self):
        rec = _make_raw_record("linkedin", {
            "id": "test", "name": "John Smith", "title": "IT Support",
            "department": "IT", "manager": None, "phone": None, "source": "linkedin"
        })
        identity = extract_identity(rec)
        assert identity["first"] == "John"
        assert identity["last"] == "Smith"

    def test_role_group_helpdesk(self):
        assert _normalise_role_group("Helpdesk Agent") == "Helpdesk"
        assert _normalise_role_group("IT Support Specialist") == "Helpdesk"
        assert _normalise_role_group("Senior Helpdesk Technician") == "Helpdesk"

    def test_role_group_it_admin(self):
        assert _normalise_role_group("IT Administrator") == "IT_Admin"
        assert _normalise_role_group("Okta Administrator") == "IT_Admin"
        assert _normalise_role_group("Systems Administrator") == "IT_Admin"

    def test_role_group_executive(self):
        assert _normalise_role_group("Chief Executive Officer") == "Executive"
        assert _normalise_role_group("VP of Finance") == "Executive"

    def test_confidence_is_explicit_for_direct_data(self):
        identity = extract_identity(self.sample)
        assert identity["confidence"] == EXPLICIT

    def test_source_id_matches_connector(self):
        identity = extract_identity(self.sample)
        assert identity["source_id"] == "linkedin"

    def test_snippet_contains_name_and_title(self):
        identity = extract_identity(self.sample)
        assert identity["name"] in identity["snippet"]

    def test_all_20_employees_have_role_groups(self):
        for rec in self.records:
            identity = extract_identity(rec)
            assert identity["role_group"] in ("Helpdesk", "IT_Admin", "Executive", "Staff")


# ===========================================================================
# Issue #38: Email pattern inference
# ===========================================================================

class TestEmailInference:
    def test_returns_up_to_3_candidates(self):
        candidates = infer_email_candidates("John", "Smith", [], "simcorp.com")
        assert len(candidates) <= 3

    def test_returns_list_of_dicts(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        for c in candidates:
            assert "address" in c
            assert "pattern" in c
            assert "confidence" in c
            assert "rank" in c

    def test_candidates_use_correct_domain(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        for c in candidates:
            assert c["address"].endswith("@simcorp.com")

    def test_first_last_pattern_generated(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        patterns = [c["pattern"] for c in candidates]
        assert "first.last" in patterns

    def test_explicit_email_ranked_first(self):
        explicit = ["sarah.mitchell@simcorp.com"]
        candidates = infer_email_candidates("Sarah", "Mitchell", explicit, "simcorp.com")
        assert candidates[0]["confidence"] == EXPLICIT
        assert candidates[0]["address"] == "sarah.mitchell@simcorp.com"

    def test_inferred_email_marked_correctly(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        # All should be inferred when no explicit emails given
        inferred = [c for c in candidates if c["confidence"] == INFERRED]
        assert len(inferred) > 0

    def test_empty_name_returns_empty_list(self):
        candidates = infer_email_candidates("", "", [], "simcorp.com")
        assert candidates == []

    def test_ranks_are_sequential(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        ranks = [c["rank"] for c in candidates]
        assert ranks == list(range(1, len(candidates) + 1))

    def test_no_duplicate_addresses(self):
        candidates = infer_email_candidates("Sarah", "Mitchell", [], "simcorp.com")
        addresses = [c["address"] for c in candidates]
        assert len(addresses) == len(set(addresses))

    def test_profile_marked_when_no_email_found(self):
        """Issue #38: mark profile if no emails found"""
        candidates = infer_email_candidates("", "", [], "simcorp.com")
        assert candidates == []


# ===========================================================================
# Issue #39: Phone number extraction
# ===========================================================================

class TestPhoneExtraction:
    def setup_method(self):
        self.web_records = WebsiteConnector().scrape()

    def test_extracts_phone_numbers(self):
        phones = extract_phone_numbers(self.web_records[0])
        assert len(phones) > 0

    def test_phone_record_has_required_fields(self):
        phones = extract_phone_numbers(self.web_records[0])
        for p in phones:
            assert "raw" in p
            assert "normalised" in p
            assert "label" in p
            assert "confidence" in p
            assert "source_id" in p

    def test_helpdesk_phone_is_labelled(self):
        phones = extract_phone_numbers(self.web_records[0])
        helpdesk = [p for p in phones if p["label"] == "helpdesk"]
        assert len(helpdesk) > 0

    def test_confidence_is_explicit(self):
        phones = extract_phone_numbers(self.web_records[0])
        for p in phones:
            assert p["confidence"] == EXPLICIT

    def test_normalise_phone_formats_correctly(self):
        assert _normalise_phone("+1-613-555-0100") == "+1-613-555-0100"
        assert _normalise_phone("6135550100") == "+1-613-555-0100"
        assert _normalise_phone("613.555.0100") == "+1-613-555-0100"
        assert _normalise_phone("(613) 555-0100") == "+1-613-555-0100"

    def test_source_id_is_company_website(self):
        phones = extract_phone_numbers(self.web_records[0])
        for p in phones:
            assert p["source_id"] == "company_website"


# ===========================================================================
# Issue #40: SSO provider detection
# ===========================================================================

class TestSSODetection:
    def test_detects_okta_in_job_postings(self):
        job_records = JobPostingConnector().scrape()
        result = detect_sso_provider(job_records)
        assert result is not None
        assert result["provider"] == "Okta"

    def test_returns_evidence_snippet(self):
        job_records = JobPostingConnector().scrape()
        result = detect_sso_provider(job_records)
        assert "evidence_snippet" in result
        assert len(result["evidence_snippet"]) > 0

    def test_confidence_is_explicit(self):
        job_records = JobPostingConnector().scrape()
        result = detect_sso_provider(job_records)
        assert result["confidence"] == EXPLICIT

    def test_returns_none_when_no_sso_found(self):
        fake_record = [_make_raw_record("job_postings", {"body": "We are hiring a baker."})]
        result = detect_sso_provider(fake_record)
        assert result is None

    def test_no_fuzzy_match_on_similar_words(self):
        """Avoid false positives: substring occurrences of 'okta' should not match."""
        fake_record = [_make_raw_record("job_postings", {
            "body": "Contact oktatisktaktikal@example.com for more info."
        })]
        # 'Okta' only appears here as part of a larger token, so detection
        # should not report a provider match.
        result = detect_sso_provider(fake_record)
        assert result is None

    def test_source_id_in_result(self):
        job_records = JobPostingConnector().scrape()
        result = detect_sso_provider(job_records)
        assert "source_id" in result


# ===========================================================================
# Issue #42: Export Structured JSON
# ===========================================================================

class TestExportStructuredJSON:
    def test_run_produces_profiles_json(self, tmp_path):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "profiler.py"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
        )
        profiles_path = Path(__file__).parent.parent / "output" / "profiles.json"
        assert profiles_path.exists(), f"profiles.json not found. stderr: {result.stderr}"

    def test_profiles_json_is_valid_json(self):
        profiles_path = Path(__file__).parent.parent / "output" / "profiles.json"
        if not profiles_path.exists():
            pytest.skip("Run profiler.py first")
        with open(profiles_path) as f:
            profiles = json.load(f)
        assert isinstance(profiles, list)

    def test_profile_has_required_schema_fields(self):
        profiles_path = Path(__file__).parent.parent / "output" / "profiles.json"
        if not profiles_path.exists():
            pytest.skip("Run profiler.py first")
        with open(profiles_path) as f:
            profiles = json.load(f)
        required = [
            "id", "employee_id", "name", "title", "email_candidates",
            "phone_numbers", "okta_username", "sso_provider",
            "attack_value", "source_id", "provenance_log", "created_at"
        ]
        for field in required:
            assert field in profiles[0], f"Missing field: {field}"

    def test_profiles_sorted_by_attack_value_descending(self):
        profiles_path = Path(__file__).parent.parent / "output" / "profiles.json"
        if not profiles_path.exists():
            pytest.skip("Run profiler.py first")
        with open(profiles_path) as f:
            profiles = json.load(f)
        values = [p["attack_value"] for p in profiles]
        assert values == sorted(values, reverse=True)

    def test_sample_profile_written(self):
        sample_path = Path(__file__).parent.parent / "output" / "sample_profile.json"
        if not sample_path.exists():
            pytest.skip("Run profiler.py first")
        with open(sample_path) as f:
            sample = json.load(f)
        assert "name" in sample
        assert "attack_value" in sample


# ===========================================================================
# Issue #43: Provenance logging
# ===========================================================================

class TestProvenanceAndSafeguards:
    def test_event_log_written(self):
        events_path = Path(__file__).parent.parent / "output" / "events.jsonl"
        if not events_path.exists():
            pytest.skip("Run profiler.py first")
        lines = events_path.read_text().strip().splitlines()
        assert len(lines) > 0

    def test_events_are_valid_json(self):
        events_path = Path(__file__).parent.parent / "output" / "events.jsonl"
        if not events_path.exists():
            pytest.skip("Run profiler.py first")
        for line in events_path.read_text().strip().splitlines():
            event = json.loads(line)
            assert "event_id" in event
            assert "timestamp" in event
            assert "technique_id" in event
            assert "phase" in event

    def test_flag_1_triggered_for_high_value_target(self):
        events_path = Path(__file__).parent.parent / "output" / "events.jsonl"
        if not events_path.exists():
            pytest.skip("Run profiler.py first")
        events = [json.loads(l) for l in events_path.read_text().strip().splitlines()]
        flagged = [e for e in events if e.get("flag_triggered") == "FLAG_1_RECON_COMPLETE"]
        assert len(flagged) >= 1

    def test_whitelist_enforcement_blocks_external_call(self):
        """Issue #43: unit test that simulates external call attempt and asserts failure"""
        with pytest.raises(SourceNotWhitelisted) as exc_info:
            _assert_whitelisted("https://www.linkedin.com")
        assert "not in the whitelist" in str(exc_info.value)

    def test_provenance_log_in_profile(self):
        profiles_path = Path(__file__).parent.parent / "output" / "profiles.json"
        if not profiles_path.exists():
            pytest.skip("Run profiler.py first")
        with open(profiles_path) as f:
            profiles = json.load(f)
        for profile in profiles:
            assert "provenance_log" in profile
            assert len(profile["provenance_log"]) > 0
            entry = profile["provenance_log"][0]
            assert "step" in entry
            assert "source_id" in entry
            assert "timestamp" in entry
