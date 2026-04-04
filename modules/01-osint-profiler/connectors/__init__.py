"""
Connector layer for the OSINT Profiler.
Issue #36 — Harvest Simulated Sources

Provides connectors for each simulated data source:
  - LinkedInConnector   (fake employee directory JSON)
  - JobPostingConnector (mock job postings feed JSON)
  - WebsiteConnector    (simulated company website HTML)

SAFETY: All connectors operate against a whitelist of allowed source IDs.
Any attempt to access a non-whitelisted source raises SourceNotWhitelisted.
No real network requests are ever made.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Whitelist — the only source IDs allowed to be scraped
# ---------------------------------------------------------------------------
WHITELISTED_SOURCES = {"linkedin", "job_postings", "company_website"}

DATA_DIR = Path(__file__).parent


class SourceNotWhitelisted(Exception):
    """Raised when a connector attempts to access a non-whitelisted source."""


def _assert_whitelisted(source_id: str) -> None:
    if source_id not in WHITELISTED_SOURCES:
        raise SourceNotWhitelisted(
            f"Source '{source_id}' is not in the whitelist. "
            f"Allowed: {WHITELISTED_SOURCES}"
        )


def _make_raw_record(source_id: str, data: Any) -> dict:
    """Wrap scraped data in a provenance envelope."""
    return {
        "scrape_id": str(uuid.uuid4()),
        "source_id": source_id,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


# ---------------------------------------------------------------------------
# LinkedIn connector — reads employees.json
# ---------------------------------------------------------------------------
class LinkedInConnector:
    SOURCE_ID = "linkedin"

    def scrape(self) -> list[dict]:
        """
        Returns a list of raw records from the simulated employee directory.
        Each record is wrapped with a provenance envelope.
        """
        _assert_whitelisted(self.SOURCE_ID)
        path = DATA_DIR / "employees.json"
        with open(path) as f:
            employees = json.load(f)
        return [_make_raw_record(self.SOURCE_ID, emp) for emp in employees]


# ---------------------------------------------------------------------------
# Job postings connector — reads job_postings.json
# ---------------------------------------------------------------------------
class JobPostingConnector:
    SOURCE_ID = "job_postings"

    def scrape(self) -> list[dict]:
        """
        Returns a list of raw records from the simulated job postings feed.
        """
        _assert_whitelisted(self.SOURCE_ID)
        path = DATA_DIR / "job_postings.json"
        with open(path) as f:
            postings = json.load(f)
        return [_make_raw_record(self.SOURCE_ID, posting) for posting in postings]


# ---------------------------------------------------------------------------
# Company website connector — parses company_website.html
# ---------------------------------------------------------------------------
class WebsiteConnector:
    SOURCE_ID = "company_website"

    # Patterns to pull from the HTML
    _PHONE_RE = re.compile(r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
    _EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    _OKTA_RE = re.compile(r"okta\.com", re.IGNORECASE)

    def scrape(self) -> list[dict]:
        """
        Parses each page of the simulated company website and returns one raw
        record per page, each containing extracted phones, emails, and Okta
        mentions. The profiler navigates all pages to assemble a full picture.
        """
        _assert_whitelisted(self.SOURCE_ID)
        website_dir = DATA_DIR / "website"
        records = []
        for html_file in sorted(website_dir.glob("*.html")):
            html = html_file.read_text()
            phones = self._PHONE_RE.findall(html)
            emails = self._EMAIL_RE.findall(html)
            okta_mentions = self._OKTA_RE.findall(html)
            data = {
                "page": html_file.name,
                "raw_html_length": len(html),
                "phones_found": phones,
                "emails_found": emails,
                "okta_mentions": len(okta_mentions),
                "source_path": str(html_file),
            }
            records.append(_make_raw_record(self.SOURCE_ID, data))
        return records
