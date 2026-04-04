"""
Extractor layer for the OSINT Profiler.

Issue #37: Extract Basic Identity Attributes
Issue #38: Infer Email Patterns
Issue #39: Collect Public Phone Numbers
Issue #40: Detect SSO Provider Mentions

Each extractor takes raw connector records and returns structured fields
with source provenance and an explicit/inferred confidence flag.
"""

import re
from collections import Counter
from typing import Optional

# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------
EXPLICIT = "explicit"   # field was directly found in source data
INFERRED = "inferred"   # field was derived / pattern-matched


# ---------------------------------------------------------------------------
# Issue #37: Identity extractor
# ---------------------------------------------------------------------------

# Maps title keywords to normalised role groups
_ROLE_MAP = [
    (["helpdesk", "it support", "support specialist", "helpdesk agent",
      "helpdesk technician"], "Helpdesk"),
    (["it administrator", "systems administrator", "sysadmin",
      "okta administrator", "network engineer", "devops", "it director",
      "director of it", "security analyst", "identity engineer"], "IT_Admin"),
    (["chief executive", "chief financial", "chief technology",
      "ceo", "cfo", "cto", "vp of", "vice president", "director"], "Executive"),
    (["finance analyst", "finance manager", "legal", "hr", "sales"], "Staff"),
]


def _normalise_role_group(title: str) -> str:
    t = title.lower()
    for keywords, group in _ROLE_MAP:
        if any(kw in t for kw in keywords):
            return group
    return "Staff"


def extract_identity(linkedin_record: dict) -> dict:
    """
    Parse a raw LinkedIn connector record and extract core identity fields.

    Returns a dict with:
      name, first, last, display_name, title, role_group,
      department, manager, source_id, snippet, confidence
    """
    emp = linkedin_record["data"]
    raw_name = emp.get("name", "")
    parts = raw_name.strip().split()
    first = parts[0] if len(parts) >= 1 else ""
    last = parts[-1] if len(parts) >= 2 else ""

    return {
        "name": raw_name,
        "first": first,
        "last": last,
        "display_name": raw_name,
        "title": emp.get("title", ""),
        "role_group": _normalise_role_group(emp.get("title", "")),
        "department": emp.get("department", ""),
        "manager": emp.get("manager"),
        "source_id": linkedin_record["source_id"],
        "scrape_id": linkedin_record["scrape_id"],
        "snippet": f"{raw_name}: {emp.get('title','')} ({emp.get('department','')})",
        "confidence": EXPLICIT,
    }


# ---------------------------------------------------------------------------
# Issue #38: Email pattern inference
# ---------------------------------------------------------------------------

_EMAIL_PATTERNS = [
    ("first.last",   lambda f, l, d: f"{f.lower()}.{l.lower()}@{d}"),
    ("f.last",       lambda f, l, d: f"{f[0].lower()}.{l.lower()}@{d}"),
    ("firstlast",    lambda f, l, d: f"{f.lower()}{l.lower()}@{d}"),
    ("first",        lambda f, l, d: f"{f.lower()}@{d}"),
]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})")


def _detect_domain_pattern(explicit_emails: list[str]) -> Optional[tuple[str, str]]:
    """
    Given a list of email addresses found explicitly in sources,
    use frequency analysis to identify the most common (pattern, domain) pair.
    Returns (pattern_name, domain) or None if not enough data.
    """
    domain_counts: Counter = Counter()
    for email in explicit_emails:
        m = _EMAIL_RE.search(email)
        if m:
            domain_counts[m.group(1)] += 1

    if not domain_counts:
        return None

    domain = domain_counts.most_common(1)[0][0]

    # Try to detect pattern by matching against known emails
    pattern_votes: Counter = Counter()
    for email in explicit_emails:
        if domain not in email:
            continue
        local = email.split("@")[0]
        # Check against patterns: we can't know first/last here so we
        # detect by structural shape
        if "." in local and len(local.split(".")[0]) > 1:
            pattern_votes["first.last"] += 1
        elif "." in local and len(local.split(".")[0]) == 1:
            pattern_votes["f.last"] += 1
        else:
            pattern_votes["firstlast"] += 1

    pattern = pattern_votes.most_common(1)[0][0] if pattern_votes else "first.last"
    return pattern, domain


def infer_email_candidates(
    first: str,
    last: str,
    explicit_emails: list[str],
    domain: str = "simcorp.com",
    known_pattern: Optional[str] = None,
) -> list[dict]:
    """
    Produce up to 3 candidate email addresses for a person.

    Returns list of dicts with: address, pattern, confidence, rank
    """
    if not first or not last:
        return []

    candidates = []

    # If we have an explicit email for this person, put it first
    for email in explicit_emails:
        if last.lower() in email.lower() or first.lower() in email.lower():
            candidates.append({
                "address": email,
                "pattern": "explicit",
                "confidence": EXPLICIT,
                "rank": 1,
            })
            break

    # Generate pattern-based candidates
    detected = _detect_domain_pattern(explicit_emails)
    if detected:
        det_pattern, det_domain = detected
    else:
        det_pattern, det_domain = known_pattern or "first.last", domain

    # Order patterns: best guess first
    ordered = [det_pattern] + [p for p, _ in _EMAIL_PATTERNS if p != det_pattern]

    rank = len(candidates) + 1
    for pattern_name in ordered:
        if rank > 3:
            break
        fn = dict(_EMAIL_PATTERNS).get(pattern_name)
        if fn is None:
            continue
        address = fn(first, last, det_domain)
        # Skip if already in candidates
        if any(c["address"] == address for c in candidates):
            continue
        confidence = EXPLICIT if pattern_name == det_pattern else INFERRED
        candidates.append({
            "address": address,
            "pattern": pattern_name,
            "confidence": confidence,
            "rank": rank,
        })
        rank += 1

    return candidates[:3]


# ---------------------------------------------------------------------------
# Issue #39: Phone number extraction
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4})")
_HELPDESK_CONTEXT = re.compile(
    r"(helpdesk|it support|support|service desk|help desk)", re.IGNORECASE
)


def _normalise_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1-{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw.strip()


def extract_phone_numbers(website_record: dict) -> list[dict]:
    """
    Extract and normalise phone numbers from a website connector record.
    Tags numbers as 'helpdesk' or 'support' when context suggests it.

    Returns list of dicts with: raw, normalised, label, confidence, source_id
    """
    data = website_record["data"]
    raw_phones = data.get("phones_found", [])

    # Re-parse from HTML to get surrounding context
    source_path = data.get("source_path", "")
    context_map: dict[str, str] = {}
    try:
        with open(source_path, encoding="utf-8") as f:
            html = f.read()
        # Build a context snippet for each phone
        for raw in raw_phones:
            idx = html.find(raw)
            if idx >= 0:
                snippet = html[max(0, idx - 80): idx + len(raw) + 80]
                context_map[raw] = snippet
    except OSError:
        pass

    results = []
    for raw in raw_phones:
        normalised = _normalise_phone(raw)
        snippet = context_map.get(raw, "")
        label = "helpdesk" if _HELPDESK_CONTEXT.search(snippet) else "general"
        results.append({
            "raw": raw,
            "normalised": normalised,
            "label": label,
            "confidence": EXPLICIT,
            "snippet": snippet.strip(),
            "source_id": website_record["source_id"],
            "scrape_id": website_record["scrape_id"],
        })
    return results


# ---------------------------------------------------------------------------
# Issue #40: SSO provider detection
# ---------------------------------------------------------------------------

_SSO_KEYWORDS = [
    "Okta", "SSO", "Single Sign-On", "Single Sign On",
    "Okta administrator", "SAML", "identity provider",
]

# Maps lowercase keyword to a canonical provider name.
# Generic SSO/SAML keywords that don't identify a specific vendor are
# labelled "Unknown" so the returned `provider` field always reflects the
# actual evidence rather than assuming Okta.
_KEYWORD_TO_PROVIDER: dict[str, str] = {
    "okta": "Okta",
    "okta administrator": "Okta",
    "sso": "Unknown",
    "single sign-on": "Unknown",
    "single sign on": "Unknown",
    "saml": "Unknown",
    "identity provider": "Unknown",
}

# Sort longest first so "Okta administrator" is tried before "Okta".
# Use word-boundary lookarounds to prevent matching inside larger tokens
# (e.g., "oktatisktaktikal" must not match "Okta").
_SSO_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(kw) for kw in sorted(_SSO_KEYWORDS, key=len, reverse=True))
    + r")(?!\w)",
    re.IGNORECASE,
)


def detect_sso_provider(records: list[dict]) -> Optional[dict]:
    """
    Scan job posting and website records for explicit SSO/Okta mentions.
    Avoids fuzzy matching to reduce false positives: exact keyword match only.

    Returns a dict with: provider, evidence_snippet, confidence, source_id
    or None if not found.  The ``provider`` value is derived from the matched
    keyword so that generic SSO language (e.g. "SAML") does not incorrectly
    attribute the result to a specific vendor.
    """
    for record in records:
        data = record["data"]
        # Get text to scan
        if isinstance(data, dict):
            text = data.get("body", "") or str(data)
        else:
            text = str(data)

        match = _SSO_RE.search(text)
        if match:
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            snippet = text[start:end].strip()
            # .lower() normalises the case-insensitively-matched token so it
            # aligns with the lowercase keys in _KEYWORD_TO_PROVIDER.
            provider = _KEYWORD_TO_PROVIDER.get(match.group(0).lower(), "Unknown")
            return {
                "provider": provider,
                "evidence_snippet": snippet,
                "confidence": EXPLICIT,
                "source_id": record["source_id"],
                "scrape_id": record["scrape_id"],
            }
    return None
