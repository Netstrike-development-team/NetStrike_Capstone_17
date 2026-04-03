"""
OSINT Profiler: Phase 1 of the Scattered Spider simulation.

Issue #36: Harvest Simulated Sources
Issue #37: Extract Basic Identity Attributes
Issue #38: Infer Email Patterns
Issue #39: Collect Public Phone Numbers
Issue #40: Detect SSO Provider Mentions
Issue #41: Generate Scenario Template
Issue #42: Export Structured JSON
Issue #43: Logging & Basic Safeguards

MITRE ATT&CK:
  T1593.001: Search Open Websites/Domains (LinkedIn OSINT)
  T1589.002: Gather Victim Identity Info (Email addresses)
  T1598.003: Phishing for Information (Target profiling)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from connectors import LinkedInConnector, JobPostingConnector, WebsiteConnector
from extractors import (
    extract_identity,
    infer_email_candidates,
    extract_phone_numbers,
    detect_sso_provider,
    EXPLICIT,
    INFERRED,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("osint-profiler")

# ---------------------------------------------------------------------------
# Target scoring
# ---------------------------------------------------------------------------

_SCORE_MAP = {
    "Helpdesk": 9,
    "IT_Admin": 8,
    "Executive": 7,
    "Staff": 4,
}

FLAG_THRESHOLD = 8  # attack_value >= this triggers FLAG_1


def _score_target(role_group: str) -> int:
    return _SCORE_MAP.get(role_group, 4)


# ---------------------------------------------------------------------------
# Scenario template generator: Issue #41
# ---------------------------------------------------------------------------

_PRETEXT_TEMPLATE = """
VISHING PRETEXT: SIMULATED EXERCISE USE ONLY
==============================================
Scenario: Senior employee locked out while travelling

CALLER SCRIPT:
"Hi, this is {name}, {title} here at SimCorp. I'm currently travelling in
{travel_location} and I'm completely locked out of my account: I can't access
my email or the {sso_provider} portal. I have a critical {urgency_event} in
{time_pressure} and I desperately need access restored.

My employee ID is {employee_id}. My manager is {manager}. Last time I logged
in I was in the Ottawa office.

Can you please reset my password and temporarily remove the MFA requirement
so I can get back in?"

KEY FACTS TO KNOW:
  Full name     : {name}
  Title         : {title}
  Department    : {department}
  Manager       : {manager}
  Email guess   : {top_email}
  Okta username : {okta_username}
  SSO provider  : {sso_provider}
  Helpdesk line : {helpdesk_phone}
  Role group    : {role_group}

LOW-CONFIDENCE FIELDS (verify before use):
{low_confidence_note}

EVIDENCE USED TO BUILD THIS PRETEXT:
{evidence_summary}
""".strip()


def _generate_pretext_template(profile: dict, helpdesk_phone: str, sso_provider: str) -> str:
    top_email = ""
    if profile.get("email_candidates"):
        top_email = profile["email_candidates"][0]["address"]

    low_conf_fields = []
    for cand in profile.get("email_candidates", []):
        if cand["confidence"] == INFERRED:
            low_conf_fields.append(f"  email '{cand['address']}' (inferred, pattern: {cand['pattern']})")

    low_confidence_note = "\n".join(low_conf_fields) if low_conf_fields else "  None: all fields explicit"

    evidence = [f"  • Source: {profile['source_id']}: {profile['snippet']}"]
    if top_email:
        conf = profile["email_candidates"][0]["confidence"]
        evidence.append(f"  • Email pattern: {profile['email_candidates'][0]['pattern']} ({conf})")

    return _PRETEXT_TEMPLATE.format(
        name=profile["name"],
        title=profile["title"],
        department=profile["department"],
        manager=profile.get("manager") or "Unknown",
        top_email=top_email or "Unknown",
        okta_username=profile.get("okta_username", ""),
        sso_provider=sso_provider,
        helpdesk_phone=helpdesk_phone,
        role_group=profile["role_group"],
        travel_location="London, UK",
        urgency_event="board presentation",
        time_pressure="20 minutes",
        employee_id=profile["employee_id"],
        low_confidence_note=low_confidence_note,
        evidence_summary="\n".join(evidence),
    )


# ---------------------------------------------------------------------------
# Event emitter: Issue #43
# ---------------------------------------------------------------------------

def _emit_event(
    phase: int,
    technique_id: str,
    tactic: str,
    description: str,
    source_module: str,
    flag: Optional[str] = None,
    raw_data: Optional[dict] = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "technique_id": technique_id,
        "tactic": tactic,
        "description": description,
        "source_module": source_module,
        "flag_triggered": flag,
        "raw_data": raw_data or {},
    }


# ---------------------------------------------------------------------------
# Main run function: Issue #42, #43
# ---------------------------------------------------------------------------

def run(
    output_dir: str = "output",
    events_path: str = "output/events.jsonl",
    domain: str = "simcorp.com",
) -> list[dict]:
    """
    Execute the full OSINT profiler pipeline and export structured JSON profiles.

    Steps:
      1. Scrape all whitelisted simulated sources
      2. Extract identity attributes from LinkedIn records
      3. Infer email candidates using frequency-based pattern detection
      4. Extract and normalise phone numbers from website
      5. Detect SSO provider from job postings and website
      6. Score each target and rank by attack value
      7. Generate pretext template for highest-value target
      8. Export validated JSON profiles
      9. Write event log entries

    Returns list of profile dicts (sorted highest attack value first).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)
    events_file = Path(events_path)

    events: list[dict] = []

    # ------------------------------------------------------------------
    # Step 1: Harvest all sources (Issue #36)
    # ------------------------------------------------------------------
    logger.info("Harvesting simulated sources...")

    li_records = LinkedInConnector().scrape()
    logger.info(f"  LinkedIn: {len(li_records)} employee records")
    events.append(_emit_event(
        phase=1, technique_id="T1593.001", tactic="reconnaissance",
        description=f"Scraped simulated LinkedIn directory: {len(li_records)} records",
        source_module="01-osint-profiler",
        raw_data={"record_count": len(li_records)},
    ))

    job_records = JobPostingConnector().scrape()
    logger.info(f"  Job postings: {len(job_records)} postings")
    events.append(_emit_event(
        phase=1, technique_id="T1598.003", tactic="reconnaissance",
        description=f"Scraped simulated job postings feed: {len(job_records)} postings",
        source_module="01-osint-profiler",
        raw_data={"record_count": len(job_records)},
    ))

    web_records = WebsiteConnector().scrape()
    logger.info(f"  Website: {len(web_records)} page(s) parsed")

    # ------------------------------------------------------------------
    # Step 2: Detect SSO provider (Issue #40)
    # ------------------------------------------------------------------
    sso_result = detect_sso_provider(job_records + web_records)
    sso_provider = sso_result["provider"] if sso_result else "Unknown SSO"
    logger.info(f"  SSO provider detected: {sso_provider}")
    if sso_result:
        events.append(_emit_event(
            phase=1, technique_id="T1598.003", tactic="reconnaissance",
            description=f"SSO provider identified: {sso_provider} via {sso_result['source_id']}",
            source_module="01-osint-profiler",
            raw_data=sso_result,
        ))

    # ------------------------------------------------------------------
    # Step 3: Extract phone numbers (Issue #39)
    # ------------------------------------------------------------------
    phone_numbers = []
    helpdesk_phone = "Unknown"
    for rec in web_records:
        phone_numbers.extend(extract_phone_numbers(rec))

    helpdesk_entries = [p for p in phone_numbers if p["label"] == "helpdesk"]
    if helpdesk_entries:
        helpdesk_phone = helpdesk_entries[0]["normalised"]
    logger.info(f"  Phones found: {len(phone_numbers)} | Helpdesk: {helpdesk_phone}")

    # ------------------------------------------------------------------
    # Step 4: Build profiles from LinkedIn records (Issues #37, #38)
    # ------------------------------------------------------------------

    # Collect all explicit emails from website for domain pattern detection
    site_emails: list[str] = []
    for rec in web_records:
        site_emails.extend(rec["data"].get("emails_found", []))

    profiles: list[dict] = []

    for li_rec in li_records:
        identity = extract_identity(li_rec)
        email_candidates = infer_email_candidates(
            first=identity["first"],
            last=identity["last"],
            explicit_emails=site_emails,
            domain=domain,
        )

        emp_data = li_rec["data"]
        attack_value = _score_target(identity["role_group"])

        profile = {
            "id": str(uuid.uuid4()),
            "employee_id": emp_data["id"],
            "name": identity["name"],
            "first": identity["first"],
            "last": identity["last"],
            "title": identity["title"],
            "role_group": identity["role_group"],
            "department": identity["department"],
            "manager": identity["manager"],
            "email_candidates": email_candidates if email_candidates else None,
            "phone_numbers": [
                p for p in phone_numbers
                if p["label"] == "helpdesk"
            ],
            "okta_username": (
                f"{identity['first'].lower()}{identity['last'].lower()}"
                if identity["first"] and identity["last"] else ""
            ),
            "sso_provider": sso_provider,
            "attack_value": attack_value,
            "source_id": identity["source_id"],
            "snippet": identity["snippet"],
            "provenance_log": [
                {
                    "step": "identity_extraction",
                    "source_id": identity["source_id"],
                    "scrape_id": identity["scrape_id"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": identity["confidence"],
                }
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        profiles.append(profile)

    # ------------------------------------------------------------------
    # Step 5: Sort by attack value, emit events
    # ------------------------------------------------------------------
    profiles.sort(key=lambda p: p["attack_value"], reverse=True)

    events.append(_emit_event(
        phase=1, technique_id="T1589.002", tactic="reconnaissance",
        description=f"Built {len(profiles)} target profiles. "
                    f"Top target: {profiles[0]['name']} ({profiles[0]['title']})",
        source_module="01-osint-profiler",
        flag="FLAG_1_RECON_COMPLETE" if profiles[0]["attack_value"] >= FLAG_THRESHOLD else None,
        raw_data={
            "total_profiles": len(profiles),
            "top_target": profiles[0]["name"],
            "top_attack_value": profiles[0]["attack_value"],
        },
    ))

    # ------------------------------------------------------------------
    # Step 6: Generate pretext template for top target (Issue #41)
    # ------------------------------------------------------------------
    top = profiles[0]
    pretext = _generate_pretext_template(top, helpdesk_phone, sso_provider)
    pretext_path = out_dir / "pretext_template.txt"
    pretext_path.write_text(pretext)
    logger.info(f"  Pretext template written to {pretext_path}")

    # ------------------------------------------------------------------
    # Step 7: Export JSON profiles (Issue #42)
    # ------------------------------------------------------------------
    profiles_path = out_dir / "profiles.json"
    with open(profiles_path, "w") as f:
        json.dump(profiles, f, indent=2)
    logger.info(f"  {len(profiles)} profiles exported to {profiles_path}")

    # Sample profile for verification
    sample_path = out_dir / "sample_profile.json"
    with open(sample_path, "w") as f:
        json.dump(profiles[0], f, indent=2)
    logger.info(f"  Sample profile (top target) written to {sample_path}")

    # ------------------------------------------------------------------
    # Step 8: Write event log (Issue #43)
    # ------------------------------------------------------------------
    with open(events_file, "a") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    logger.info(f"  {len(events)} events written to {events_file}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 55)
    logger.info("OSINT PROFILER COMPLETE")
    logger.info("=" * 55)
    logger.info(f"  Total profiles   : {len(profiles)}")
    logger.info(f"  Top target       : {top['name']} ({top['title']})")
    logger.info(f"  Attack value     : {top['attack_value']}/10")
    logger.info(f"  SSO provider     : {sso_provider}")
    logger.info(f"  Helpdesk phone   : {helpdesk_phone}")
    logger.info(f"  FLAG 1 triggered : {top['attack_value'] >= FLAG_THRESHOLD}")
    logger.info("=" * 55)

    return profiles


if __name__ == "__main__":
    run()
